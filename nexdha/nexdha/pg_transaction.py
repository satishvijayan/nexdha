from __future__ import unicode_literals
import frappe, math
from frappe import _
from frappe.utils import flt
from frappe.model.mapper import get_mapped_doc
from frappe.model.document import Document
from frappe.contacts.doctype.address.address import get_company_address
from frappe.contacts.doctype.address.address import get_default_address 
from erpnext.accounts.doctype.tax_rule.tax_rule import get_tax_template
from erpnext.accounts.party import get_party_account
# from erpnext.regional.india.utils import validate_gstin_check_digit   #for validating gstin structure
# from erpnext.regional.india.utils import validate_pan_for_india       #for validating PAN structure
# from erpnext.controllers.taxes_and_totals import get_itemised_tax, get_itemised_taxable_amount #get itemised tax
# from erpnext.regional.india.utils import calculate_annual_eligible_hra_exemption # relevant to payroll!
# from erpnext.regional.india.utils import update_taxable_values        # updates tax for each row...
# from erpnext.stock.get_item_details import  _get_item_tax_template, get_item_tax_map

def name_customer(doc, method):
    if doc.nexdha_user_id:
        # doc.name = "CUST-FROM-MYAPP-{}".format(doc.my_own_id)
        doc.name="EXT-" + str(doc.nexdha_user_id)


def wrapstring(s):
    return '"' + str(s) + '"' if s else  ''


def find_next_working_day(date = frappe.utils.nowdate(), days = 1):
    next_working_day=frappe.utils.add_days(date,days)
    if frappe.get_value("Holiday",{'holiday_date': next_working_day},'holiday_date'):
        find_next_working_day(next_working_day,1)
    else:
        return next_working_day

# customer_state=pg_tran.customer_state
# nexdha_user_id=pg_tran.nexdha_user_id
# customer_name=pg_tran.customer_name
# customer_phone= pg_tran.customer_phone
# transaction_type =pg_tran.transaction_type
# transaction_source =pg_tran.transaction_source
# transaction_date = pg_tran.transaction_date
# transaction_reference =pg_tran.transaction_reference_number
# pg_settlement_date =pg_tran.pg_settlement_date
# charged_amount=pg_tran.charged_amount
# settled_amount =pg_tran.settled_amount
# commission_amount = pg_tran.commission_amount
# eta = pg_tran.eta
# submit_transaction_initiation_jv =pg_tran.submit_transaction_initiation_jv
# submit_settlement_into_nodal_jv = pg_tran.submit_settlement_into_nodal_jv
# submit_beneficiary_settlement_jv = pg_tran.submit_beneficiary_settlement_jv
# submit_customer_invoice = pg_tran.submit_customer_invoice
# customer_record = pg_tran.customer_record
# customer_invoice = pg_tran.customer_invoice
# transaction_initiation_jv= pg_tran.transaction_initiation_jv
# settlement_into_nodal_jv = pg_tran.settlement_into_nodal_jv
# beneficiary_settlement_jv = pg_tran.beneficiary_settlement_jv
# payment_gateway = pg_tran.payment_gateway

@frappe.whitelist()
def submit_nexdha_cc2casa_transaction(doc, method):
    
    stx_doctype='Nexdha CC2CASA Transaction'
    spg_setup_doctype='Payment Gateway Setup'
    pg_tran=doc # too lazy to refactor
    company = doc.company = doc.company if doc.company else frappe.db.get_default("Company")
    
    # PG details are critical
    if not doc.payment_gateway:
        frappe.msgprint("ERROR - no PG Name on transaction - accounting entries NOT PASSED")
        return


    doc.url = frappe.utils.get_url_to_form(stx_doctype, doc.name) #new variable on doc to save url

    #PG DEFAULTS AND TRANSACTION DEFAULTS
    doc.payment_gateway_setup = frappe.get_cached_doc(spg_setup_doctype, doc.payment_gateway) #new variable for pg setup information
    doc.pg_transaction_defaults = frappe.get_cached_doc('PG Transactions Defaults',company)  #new variable for pg transaction defaults
    #new variable for default_state 
    doc.default_gst_state = get_company_address(company).gst_state or doc.pg_transaction_defaults.default_gst_state
    
    #GET ITEM CODE FOR PAYMENT GATEWAY SERVICE PROVIDED    
    doc.pg_service_type_item_code = frappe.get_value("Item", doc.pg_service_type_item_code)
    doc.pg_service_type_item_code = doc.pg_service_type_item_code \
                                    if doc.pg_service_type_item_code \
                                    else doc.payment_gateway_setup.default_item_service_code
    doc.supplier_item_code = frappe.get_cached_doc("Item",doc.pg_service_type_item_code)
    
    #GET ITEM CODE FOR CUSTOMER SERVICE PROVIDED
    # Transaction_type is the type of service availed by the customer. (t0, t1 etc)
    doc.transaction_type = frappe.get_value("Item", doc.transaction_type)
    doc.transaction_type =   doc.transaction_type \
                            if doc.transaction_type \
                            else doc.pg_transaction_defaults.customer_default_service_item

    doc.customer_item_code = frappe.get_cached_doc("Item",doc.transaction_type)

    # USE PG RATE ON TRANSACTION BY DEFAULT. IF NOT AVAILABLE LOOK UP THE PG AND GET DEFAULT RATE FOR SERVICE PROVIDED
    if not doc.pg_commission_percent:
        for row in doc.payment_gateway_setup.payment_gateway_settlement_rates:
                if row.active and row.rate_active_from <= transaction_date <= row.active_to \
                        and doc.pg_service_type_item_code== row.service_item:
                    doc.pg_commission_percent = row.pg_reference_rate
                    break
    
    

    # Set Customer_record field . CREATE CUSTOMER IF NOT AVAILABLE. 
    doc.customer_record = get_make_customer(pg_tran=doc,add_if_missing=True ).name

    # new dict variables, storing item tax, accounts and amount
    
    

    # SUPPLIER TAX CALC
    supplier_fees= flt(doc.pg_commission_percent*doc.charged_amount/100) #pg_rate*total_amount
    tax_category = frappe.get_cached_doc('Supplier', doc.payment_gateway_setup.payment_gateway_supplier).tax_category
    if not tax_category:
        tax_category=doc.pg_transaction_defaults.local_supplier_tax_category
    item_group = doc.supplier_item_code.item_group
    tax_type = 'Purchase' # Tax rules document defines as such
    
    # frappe.msgprint(" | supplier: " + tax_category )

    doc.supplier_tax = get_taxes(company=doc.company, tax_type=tax_type,transaction_date=doc.transaction_date \
                                , tax_category=tax_category , item_group=item_group \
                                , invoice_amount=supplier_fees, amt_inclusive_of_sales_tax=False)
    # frappe.msgprint('Supplier')

    # Customer TAX CALC
    customer_fees = doc.charged_amount-doc.settled_amount
    tax_category = frappe.get_cached_doc('Customer', doc.customer_record).tax_category
    if not tax_category:
        tax_category=doc.pg_transaction_defaults.local_customer_tax_category
    item_group = doc.customer_item_code.item_group
    tax_type = 'Sales' # Tax rules document defines as such

    doc.customer_tax = get_taxes( company=doc.company, tax_type=tax_type, transaction_date=doc.transaction_date \
                                , tax_category=tax_category , item_group=item_group \
                                , invoice_amount=customer_fees, amt_inclusive_of_sales_tax=True)

    doc.transaction_initiation_jv= get_make_jv(doc=doc, type='transaction_initiation_jv').name
    # doc.settlement_into_nodal_jv= get_make_jv(pg_tran=doc, type='settlement_into_nodal_jv').name
    # doc.beneficiary_settlement_jv=get_make_jv(pg_tran=doc, type='beneficiary_settlement_jv').name
    # doc.customer_invoice = get_make_invoice(pg_tran=doc, type='customer_invoice').name

# returns taxes as a dict. Each dict item has the following:
#    {
#     'tax_account': row.tax_type,
#     'tax_rate': flt(row.tax_rate/100),
#     'tax_amount':0,
#     'invoice_amount':0
#     }
@frappe.whitelist() 
def get_taxes(  company, tax_type, transaction_date, tax_category=None, item_group=None, invoice_amount=0.00 \
                ,  amt_inclusive_of_sales_tax=False, customer_group=None,supplier_group=None):
    
    args = {
            'item_group': item_group,
            'tax_category': tax_category,
            'company': company,
            'tax_type': tax_type,
            'customer_group':customer_group,
            'supplier_group': supplier_group
        }

    # frappe.msgprint("Item_group: " + args['item_group'] +  "| posting_date: " + str(args['posting_date']) + " | tax_type: " + args['tax_type'])
    
    tax_template_name = get_tax_template(transaction_date, args)
    # frappe.msgprint(tax_template_name)
    tax_template = frappe.get_cached_doc("Item Tax Template", tax_template_name)
    # frappe.msgprint(tax_template.)
    i=0
    tot_tax = 0.00
    tot_tax_rate=0.00
    tax={}
    for row in tax_template.taxes: 
        tax[i] = {
            'tax_account': row.tax_type,
            'tax_rate': flt(row.tax_rate/100),
            'tax_amount':0,
            'invoice_amount':0
            }
        i+=1
        tot_tax_rate += flt(row.tax_rate/100)
        
    invoice_amount = round(invoice_amount/(1+tot_tax_rate),2) if amt_inclusive_of_sales_tax else round(invoice_amount,2)
    # tot_tax= flt(invoice_amt*tot_tax_rate)
    for key,value in tax.items():
        value['tax_amount']=round(flt(invoice_amount*value['tax_rate']),2)
        value['invoice_amount']=invoice_amount
        
        frappe.msgprint("key:"+ str(key) + " tax_account:" + value['tax_account'] \
                        + " tax rate: " + str(value['tax_rate']) + " tax_amount: " + str(value['tax_amount']) \
                        + " invoice_amount: " + str(value['invoice_amount']) \
                        )

    return tax

        
        


@frappe.whitelist()
def get_make_jv(doc=None,  type=None):
    # return
    if not doc or not type:
        return
    
    sType1 = 'transaction_initiation_jv'
    sType2 = 'settlement_into_nodal_jv'
    sType3 = 'beneficiary_settlement_jv'


    jv = frappe.new_doc('Journal Entry')
    jv.company=doc.company

    if type == sType1:
        jv.posting_date = doc.transaction_date
        jv.mode_of_payment = doc.payment_gateway_setup.pg_payment_mode
        jv.cheque_no = doc.transaction_reference_number
        jv.cheque_date = doc.transaction_date
        jv.user_remark =    "<b> PG Transaction JV (Clearance Account Entry): </b> "                   #Automatically generated jv created on " + str(frappe.utils.formatdate(frappe.utils.nowdate())) \
        
        # rounding_diff = round(doc.charged_amount,2)-round(doc.supplier_tax[0]['invoice_amount'],2) - round((doc.charged_amount - doc.supplier_tax[0]['invoice_amount']),2)
        
        
        # Journal Entry#1
        ##1 Credit Customer: 102.5 | Amount charged to the card
        ##2 Debit Payment Gateway: 1.18 (if 1% fees) | this is the amount charged by PG to Nexhda. Nodal account gets the balance after deduction
        ##3 Debit Clearance Account: 101.32 | balance gets into clearance account, for reconciliation post settlement by PG

        # Customer Credit Entry for total amount charged to card
        row = jv.append("accounts",
                    {
                        
                        'party_type': 'Customer',
                        'party': doc.customer_record,
                        'account': get_party_account(party_type='Customer',party=doc.customer_record,company= doc.company),
                        'debit_in_account_currency': 0,
                        'credit_in_account_currency':doc.charged_amount
                        
                    }
                )

        # PG Fees Debit Entry - supplier fees are captured here, as an advance.
        row = jv.append("accounts",
                    {
                        
                        'party_type': 'Supplier',
                        'party': doc.payment_gateway_setup.payment_gateway_supplier,
                        'account': get_party_account('Supplier',doc.payment_gateway_setup.payment_gateway_supplier, doc.company),
                        'debit_in_account_currency': doc.supplier_tax[0]['invoice_amount'],
                        'credit_in_account_currency':0,
                        'is_advance': 'Yes'
                    }
                )
        # Clearance Account Entry
        row = jv.append("accounts",
                    {
                        'account': doc.payment_gateway_setup.settlement_clearance_account,
                        'debit_in_account_currency': doc.charged_amount - doc.supplier_tax[0]['invoice_amount'],
                        'credit_in_account_currency':0
                    }
                )

        try:
            jv.insert(ignore_permissions=True)
        except:
            frappe.throw("Initial JV")
            return {}

        return jv

    elif type == sType2:
        return
    elif type == sType3:
        return

@frappe.whitelist()
def get_make_customer(pg_tran=None,  add_if_missing=False):
    # check if the Nexdha_user_id has already been created in the DB. 
    cust=c=None
    c = frappe.db.get_value("Customer", {"nexdha_user_id": pg_tran.nexdha_user_id }, "name")
    if c:
        cust = frappe.get_cached_doc('Customer', c)
        # print("C:" + c.customer_name)
    
    elif add_if_missing:
        company = pg_tran.company
        
        # default_tax_category = 
        
        cust_state = frappe.db.get_value("States And Provinces",{"state_province_name": pg_tran.customer_state}, "state_province_name") or \
                     frappe.db.get_value("States And Provinces",{"abbrev": pg_tran.customer_state}, "state_province_name") or \
                     frappe.db.get_value("States And Provinces",{"alias": pg_tran.customer_state}, "state_province_name") or \
                     pg_tran.default_gst_state
        
        # frappe.msgprint("Cust_State: " + cust_state + " | Default State:" + default_state)
        
        cust = frappe.new_doc('Customer')

        cust.customer_name=pg_tran.customer_name
        cust.nexdha_user_id=pg_tran.nexdha_user_id
        cust.customer_type = 'Company' if pg_tran.customer_gst else 'Individual' #hardcoded. need to improve logic!
        cust.customer_group = pg_tran.pg_transaction_defaults.default_customer_group
        
        cust.tax_category = pg_tran.pg_transaction_defaults.local_customer_tax_category \
                            if cust_state == pg_tran.default_gst_state else pg_tran.pg_transaction_defaults.interstate_customer_tax_category


        cust.insert(ignore_permissions=True)

        # frappe.msgprint("Tax Category: " + cust.tax_category)
        
        # create address 
        cust_addr = frappe.new_doc('Address')
        cust_addr.address_title = cust.nexdha_user_id
        cust_addr.address_line1 = cust_state
        cust_addr.gst_state = cust_state
        cust_addr.tax_category = cust.tax_category
        cust_addr.city = cust_state
        cust_addr.phone=pg_tran.customer_phone
        cust_addr.gstin = pg_tran.customer_gst 

        row = cust_addr.append( "links", {
                'link_doctype': 'Customer',
                'link_name': cust.name
        })
        cust_addr.insert(ignore_permissions=True)

        


    return cust



@frappe.whitelist()
def cancel_nexdha_cc2casa_transaction(doc, method=None):
    frappe.msgprint("Cancel")



# -----------------------------------------------------
# @frappe.whitelist()
# def create_payment_entry_bank_transaction(bank_transaction_name, payment_row_doc_type, payment_entry=None):
#     B = bank_transaction_name
#     P = payment_row_doc_type
#     bt_doc = frappe.get_doc("Bank Transaction",  bank_transaction_name)
#     dt = bt_doc.date
#     ref = bt_doc.reference_number if bt_doc.reference_number else "None"
#     desc = bt_doc.description if bt_doc.description else "No Description Provided"
#     pay = bt_doc.withdrawal
#     receive = bt_doc.deposit
#     Bank=bt_doc.bank_account
#     DefComp=bt_doc.company
#     DefBank= frappe.get_value('Bank Account',{"name": Bank},  'account', )
#     DefExp = frappe.get_value('Company',{"name": DefComp},  'unreconciled_expenses_account')
#     # frappe.msgprint(DefBank)
#     # frappe.msgprint(P)
#     # frappe.msgprint(bt_doc.payment_entry(payment_row_idx).payment_document)
    
#     BT_URL=frappe.utils.get_url_to_form(bt_doc.doctype, bt_doc.name)
#     # frappe.msgprint(payment_entry)
#     # frappe.msgprint(not payment_entry)

#     if  not payment_entry:
#         if P == 'Journal Entry' :
#             doc = frappe.new_doc(P)
#             doc.voucher_type= 'Bank Entry'
#             doc.posting_date = dt
#             doc.cheque_no=ref
#             doc.cheque_date= dt
#             doc.reference= ref
#             doc.clearance_date= dt
#             doc.user_remark= desc \
#                             + "\n\n<b>Bank Statement Details:</b>" \
#                             + "\n 1. Tx Amount: " + str(pay+receive) \
#                             + "\n 2. Tx Date: " + str(frappe.utils.formatdate(dt,"dd-MMM-yyyy"))  \
#                             + "\n 3. Bank Ref: " + ref  \
#                             + "\n 4. Bank Transaction Document Reference: " + "<a href=" + BT_URL + ">" + bt_doc.name + "</a>" \
#                             + "\n\nEntry generated from Bank Transaction using 'Create Button' on: " + str(frappe.utils.formatdate(frappe.utils.nowdate(), "dd-MMM-yyyy"))
            
#             row = doc.append( "accounts",
#                         {
#                             'account': DefBank,
#                             'debit_in_account_currency': pay,
#                             'credit_in_account_currency': receive
#                         }
#                     )
#             row = doc.append( "accounts",
#                         {
#                             'account': DefExp,
#                             'debit_in_account_currency': receive,
#                             'credit_in_account_currency': pay
#                         })
#             doc.insert(ignore_permissions=True)
#             # frappe.msgprint("JV")
#             return doc.as_dict()


#         elif P == 'Payment Entry':
#             doc = frappe.new_doc(P)        
#             doc.posting_date= dt

#             doc.mode_of_payment= frappe.get_value('Company',{"name": DefComp},  'default_payment_mode')
#             doc.bank_account=DefBank
#             doc.received_amount= doc.paid_amount = pay + receive
#             # doc.total_allocated_amount = doc.base_total_allocated_amount =0
#             doc.paid_from_account_currency=doc.paid_to_account_currency =frappe.get_value('Company',{"name": DefComp},  'default_currency')
#             doc.source_exchange_rate=doc.target_exchange_rate=1
#             doc.reference_no=bt_doc.name
#             doc.reference_date=dt
#             doc.custom_remarks=1 # custom remarks describing the information avl in bank statement
#             doc.remarks=  "<b>Bank Statement Details:</b>" \
#                             + "\n 1. Amount: " + str(doc.paid_amount) \
#                             + "\n 2. Date: " + str(frappe.utils.formatdate(dt,"dd-MMM-yyyy"))  \
#                             + "\n 3. Bank Ref: " + ref  \
#                             + "\n 4. Bank Transaction Document Reference: " + "<a href=" + BT_URL + ">" + bt_doc.name + "</a>" \
#                             + "\n\nEntry generated from Bank Transaction using 'Create Button' on: " + str(frappe.utils.formatdate(frappe.utils.nowdate(), "dd-MMM-yyyy"))
#             if receive>0:
#                 doc.payment_type = 'Receive'
#                 doc.paid_from = frappe.get_value('Company',{"name": DefComp},  'default_receivable_account')
#                 doc.paid_to =   DefBank
#                 doc.party_type = "Customer"
#                 doc.party=frappe.get_value('Company',{"name": DefComp},  'default_customer_for_bank_transaction')
                
#             else :
#                 doc.payment_type = 'Pay'
#                 doc.paid_from = DefBank
#                 doc.paid_to =   frappe.get_value('Company',{"name": DefComp},  'default_payable_account')
#                 doc.party_type = "Supplier"
#                 doc.party=frappe.get_value('Company',{"name": DefComp},  'default_supplier_for_bank_transaction')            

#             doc.insert(ignore_permissions=True)            
            
#             return doc

#         elif P == 'Expense Claim':
#             return None


#     return None





# frappe.msgprint(doc.customer_record)
    # doc.save(ignore_permissions=True)

    # transaction_initiation_jv=None
    # settlement_into_nodal_jv=None
    # beneficiary_settlement_jv=None
    # sales_invoice=None
    # return frappe._dict({
    #     'customer': customer.name
    #     # 'transaction_initiation_jv': transaction_initiation_jv.name,
    #     # 'settlement_into_nodal_jv': settlement_into_nodal_jv.name,
    #     # 'beneficiary_settlement_jv':beneficiary_settlement_jv.name,
    #     # 'customer_invoice': sales_invoice.name
    # })



    # customer_state=pg_tran.customer_state
    # nexdha_user_id=pg_tran.nexdha_user_id
    # customer_name=pg_tran.customer_name
    # customer_phone= pg_tran.customer_phone
    # transaction_type =pg_tran.transaction_type
    # transaction_source =pg_tran.transaction_source
    # transaction_date = pg_tran.transaction_date
    # transaction_reference =pg_tran.transaction_reference_number
    # pg_settlement_date =pg_tran.pg_settlement_date
    # charged_amount=pg_tran.charged_amount
    # settled_amount =pg_tran.settled_amount
    # commission_amount = pg_tran.commission_amount
    # eta = pg_tran.eta
    # submit_transaction_initiation_jv =pg_tran.submit_transaction_initiation_jv
    # submit_settlement_into_nodal_jv = pg_tran.submit_settlement_into_nodal_jv
    # submit_beneficiary_settlement_jv = pg_tran.submit_beneficiary_settlement_jv
    # submit_customer_invoice = pg_tran.submit_customer_invoice
    # customer_record = pg_tran.customer_record
    # customer_invoice = pg_tran.customer_invoice
    # transaction_initiation_jv= pg_tran.transaction_initiation_jv
    # settlement_into_nodal_jv = pg_tran.settlement_into_nodal_jv
    # beneficiary_settlement_jv = pg_tran.beneficiary_settlement_jv