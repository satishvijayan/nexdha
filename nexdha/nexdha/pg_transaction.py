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
from erpnext.controllers.accounts_controller import AccountsController
# from erpnext.regional.india.utils import validate_gstin_check_digit   #for validating gstin structure
# from erpnext.regional.india.utils import validate_pan_for_india       #for validating PAN structure
# from erpnext.controllers.taxes_and_totals import get_itemised_tax, get_itemised_taxable_amount #get itemised tax
# from erpnext.regional.india.utils import calculate_annual_eligible_hra_exemption # relevant to payroll!
# from erpnext.regional.india.utils import update_taxable_values        # updates tax for each row...
from erpnext.stock.get_item_details import  get_default_income_account      #_get_item_tax_template, get_item_tax_map

def name_customer(doc, method):
    if doc.nexdha_user_id:
        # doc.name = "CUST-FROM-MYAPP-{}".format(doc.my_own_id)
        doc.name = "UID:" + str(doc.nexdha_user_id) + "|name:" + doc.customer_name


def wrapstring(s):
    return '"' + str(s) + '"' if s else  ''


def find_next_working_day(date = frappe.utils.nowdate(), days = 1):
    # date = 
    next_working_day=frappe.utils.add_days(date,days)   #get next day and format into YYYY-MM-DD
    
    if frappe.get_value("Holiday",{'holiday_date': frappe.utils.formatdate(date,"yyyy-MM-dd")},'holiday_date'):
        find_next_working_day(next_working_day,1)
    
    # frappe.msgprint("from find_next_working_day: " + str(next_working_day))
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
    transaction_date = frappe.utils.getdate(doc.transaction_date)
    
    # PG details are critical
    if not doc.payment_gateway:
        frappe.throw("ERROR - no PG Name on transaction - accounting entries NOT PASSED")
        return

    # if doc.settled_amount==doc.charged_amount:
    #     frappe.throw("Settled amount is same as charged amount, cannot create JV")


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
   
    # Set Customer_record field . CREATE CUSTOMER IF NOT AVAILABLE. 
    doc.customer_record = get_make_customer(pg_tran=doc,add_if_missing=True ).name

    # new dict variables, storing item tax, accounts and amount
    
    

    ###### SUPPLIER TAX & FEES CALC#######
    # Fees may be calculated as follows
    # 'Rate' - charged_amount * rate
    # 'Flat Fee' - flat fee regardless of volume (UPI)
    # 'Flat Fee' + Rate' - base fee + charged_amt*rate
    # 'Minimum Flat Fee with Rate' - [amt < 1/pg_rate => charge flat fee]. [amt> 1/pg_rate => charged_amt*raet
    # 'Flat rate / charge by slab' - not calculated here. PG_Commission to be supplied by external system
    # Logic is only used if we don't have 'Commission Percent'  and 'Commission Rate' on transaction document
    if doc.pg_commission_amount:
        supplier_fees=flt(doc.pg_commission_amount)
    else:
        if doc.pg_commission_percent:
            supplier_fees=flt(doc.pg_commission_percent*doc.charged_amount/100)
        else:
            for row in doc.payment_gateway_setup.payment_gateway_settlement_rates:
                if row.active and row.rate_active_from <= transaction_date <= row.rate_active_to \
                        and doc.pg_service_type_item_code== row.service_item:
                    doc.pg_commission_percent = row.pg_reference_rate
                    doc.pg_flat_fee = row.pg_flat_fee
                    doc.pg_fee_calculation = row.pg_fee_calculation #fee calc in Rate, Flat Fee, Flat Fee + Rate, Minimum Flat Fee with Rate
                    break 
        
            if doc.pg_fee_calculation=='Rate' or not doc.pg_fee_calculation:
                supplier_fees= flt(doc.pg_commission_percent*doc.charged_amount/100)
            elif doc.pg_fee_calculation=='Flat Fee':
                supplier_fees=doc.pg_flat_fee
            elif doc.pg_fee_calculation=='Flat Fee + Rate':
                supplier_fees= flt(doc.pg_flat_fee) + flt(doc.pg_commission_percent*doc.charged_amount/100)
            elif doc.pg_fee_calculation=='Minimum Flat Fee with Rate':
                supplier_fees = flt(doc.pg_commission_percent*doc.charged_amount/100) if doc.charged_amount > 100/doc.pg_commission_percent \
                                else doc.pg_flat_fee
            else:
                frappe.throw("Unable to calculate Supplier Fees. Please validate data for Document Reference : " + doc.transaction_reference_number)


    
    tax_category = frappe.get_cached_doc('Supplier', doc.payment_gateway_setup.payment_gateway_supplier).tax_category
    if not tax_category:
        tax_category=doc.pg_transaction_defaults.local_supplier_tax_category
    # item_group = 
    tax_type = 'Purchase' # Tax rules document defines as such
    
    # frappe.msgprint(" | supplier: " + tax_category )
    doc.supplier_items_dict={}
    doc.supplier_items_dict[doc.supplier_item_code.name] = get_taxes(company=doc.company, tax_type=tax_type \
                                , transaction_date=doc.transaction_date \
                                , tax_category=tax_category , item_group=doc.supplier_item_code.item_group \
                                , item=doc.supplier_item_code.name \
                                , invoice_amount=supplier_fees, amt_inclusive_of_sales_tax=False)
                        
    # frappe.msgprint('Supplier')

    # Customer TAX CALC
    customer_fees = doc.charged_amount-doc.settled_amount
    tax_category = frappe.get_cached_doc('Customer', doc.customer_record).tax_category
    if not tax_category:
        tax_category=doc.pg_transaction_defaults.local_customer_tax_category
    item_group = doc.customer_item_code.item_group
    tax_type = 'Sales' # Tax rules document defines as such
    doc.customer_items_dict={}
    doc.customer_items_dict[doc.customer_item_code.name] = get_taxes( company=doc.company, tax_type=tax_type, transaction_date=doc.transaction_date \
                                , tax_category=tax_category , item_group=item_group \
                                , item=doc.customer_item_code.name \
                                , invoice_amount=customer_fees, amt_inclusive_of_sales_tax=True)

    transaction_initiation_jv= get_make_jv(doc=doc, type='transaction_initiation_jv')
    settlement_into_nodal_jv= get_make_jv(doc=doc, type='settlement_into_nodal_jv')
    beneficiary_settlement_jv=get_make_jv(doc=doc, type='beneficiary_settlement_jv')

    
    customer_invoice = get_make_invoice(party_type = 'Customer' \
                                        , party=doc.customer_record\
                                        , invoice_date=doc.eta, posting_date=doc.eta  \
                                        , invoice_items_dict= doc.customer_items_dict \
                                        , transaction_ref=doc.transaction_reference_number \
                                        )
    doc.transaction_initiation_jv=transaction_initiation_jv.name if transaction_initiation_jv else None
    doc.settlement_into_nodal_jv=settlement_into_nodal_jv.name if settlement_into_nodal_jv else None
    doc.beneficiary_settlement_jv = beneficiary_settlement_jv.name if beneficiary_settlement_jv else None
    doc.customer_invoice=customer_invoice.name if customer_invoice else None

    ###################CROSS-REFERENCES IN REMARKS SECTION
    ref_docs=get_tx_docs(doc,True)

    date = frappe.utils.nowdate()
    ref_url = frappe.utils.get_url_to_form(doc.doctype, doc.name)
    
    remarks = "\nDocuments Created Date : " + str(frappe.utils.formatdate(date,"yyyy-MM-dd"))
    remarks+= f"\nOriginated from DocType: '{doc.doctype}' \nDocument Link: " + "<a href=" + ref_url + ">" + doc.customer_name +"->" + doc.transaction_reference_number + "</a>" 
    i=1
    for key, ref_doc in ref_docs.items():
        if not ref_doc['name']:
            continue
        # frappe.msgprint("Remarks:"+ref_doc['doctype']) 
        ref_url = frappe.utils.get_url_to_form(ref_doc['doctype'], ref_doc['name'])
        remarks += f"\n{i}. doctype: {ref_doc['doctype']} \ndoc_ref: " + "<a href=" + ref_url + ">" +ref_doc['name'] + "</a>" 
        i+=1

    # frappe.msgprint(remarks)
    #########################TRY BLOCK ###############################################
    #########################ADD REMARKS, TO JV AND INVOICE. DON'T SUBMIT INVOICE ####
    try:
        for key, ref_doc in ref_docs.items():
            if ref_doc['name']:
                
                if ref_doc['doctype']=="Sales Invoice":
                    ref_doc['doc'].remarks+=remarks
                    ref_doc['doc'].save(ignore_permissions=True)
                    # frappe.msgprint("from sales saved: " + ref_doc['doc'].name)
                else:
                    ref_doc['doc'].user_remark+=remarks
                    ref_doc['doc'].save(ignore_permissions=True)
                    if ref_doc['submit']==1:
                        ref_doc['doc'].submit()
                    # frappe.msgprint("from JV saved: " + ref_doc['doc'].name +" | Doc Status: " + str(ref_doc['doc'].docstatus))
    except Exception as e:
        template = "When adding remarks to reference documents: " + doc.customer_name + "| Tx Ref: " \
                    + doc.transaction_reference_number \
                    + "an exception of type {0} occurred, arguments:\n{1!r}"
        message = template.format(type(e).__name__, e.args)
        # frappe.msgprint(type(e))
        # frappe.msgprint(str(frappe.DoesNotExistError))
        frappe.throw(message)
    
    ###########################INVOICE PAYMENT ENTRY (can only be made after all changes)###########
    try:
        if customer_invoice and beneficiary_settlement_jv and  doc.submit_customer_invoice==1:
            beneficiary_settlement_jv.reload()
            customer_invoice.reload()
            if beneficiary_settlement_jv.docstatus==1:
                payment_doc = frappe.get_doc("Journal Entry Account", {
                                            'parenttype': 'Journal Entry'
                                            , 'parent': beneficiary_settlement_jv.name
                                            , 'party_type': 'Customer'
                                            , 'party': doc.customer_record
                                            , 'is_advance': 'Yes'
                                })
                pmt_amt = payment_doc.debit_in_account_currency + payment_doc.credit_in_account_currency
                # frappe.msgprint("line 251 - RETRIEVED payment_doc" + str(pmt_amt))
                row = customer_invoice.append("advances",{
                                                'doctype': "Sales Invoice Advance"
                                                , 'parenttype': customer_invoice.doctype
                                                , 'parent': customer_invoice.name
                                                , 'reference_row': payment_doc.name
                                                , 'reference_type': payment_doc.parenttype
                                                , 'reference_name': beneficiary_settlement_jv.name
                                                , 'advance_amount': pmt_amt
                                                , 'allocated_amount': pmt_amt
                                                , 'remarks': "Automatic Allocation from: Nexdha CCC2CASA Transaction"
                                                # , "ref_exchange_rate": 1
                                            })
            
            
            customer_invoice.save(ignore_permissions=True)            
            # frappe.msgprint("reloaded")
            customer_invoice.submit()



    except Exception as e:
        template = "When adding payments  to invoice documents: " + doc.customer_name + "| Tx Ref: " \
                    + doc.transaction_reference_number \
                    + "an exception of type {0} occurred, arguments:\n{1!r}"
        message = template.format(type(e).__name__, e.args)
        # frappe.msgprint(type(e))
        # frappe.msgprint(str(frappe.DoesNotExistError))
        frappe.throw(message)

############################################################################
# returns taxes as a dict. Each dict item has the following:
#    {
#     'tax_account': row.tax_type,
#     'tax_rate': flt(row.tax_rate/100),
#     'tax_amount':0,
#     'invoice_amount':0
#     }
# get item INVOICE AMOUNT AND TAX details NEED TO REFACTOR NAME######################################################
@frappe.whitelist() 
def get_taxes(  company, tax_type, transaction_date, tax_category=None, item_group=None, item=None \
                ,qty=1, invoice_amount=0.00,  amt_inclusive_of_sales_tax=False \
                , customer_group=None,supplier_group=None):
    
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
    # frappe.msgprint(tax_template.name)
    i=0
    tot_tax = 0.00
    tot_tax_rate=0.00
    tax={}
    for row in tax_template.taxes: 
        tax[i] = {
            'item': item
            , 'item_group': item_group
            , 'tax_account': row.tax_type
            , 'tax_rate': flt(row.tax_rate/100)
            , 'qty':qty
            , 'tax_amount':0
            , 'invoice_amount':0
            , 'tot_tax_amount':0
            }
        i+=1
        tot_tax_rate += flt(row.tax_rate/100)
        
    invoice_amount = round(invoice_amount/(1+tot_tax_rate),2) if amt_inclusive_of_sales_tax else round(invoice_amount,2)
    tot_tax_amount = round(invoice_amount*tot_tax_rate,2)
    # tot_tax= flt(invoice_amt*tot_tax_rate)
    for key,value in tax.items():
        value['tax_amount']=round(flt(invoice_amount*value['tax_rate']),2)
        value['invoice_amount']=invoice_amount
        value['tot_tax_amount']=tot_tax_amount
        
        frappe.msgprint("key:"+ str(key) + " Type " + tax_type + " tax_account:" + value['tax_account'] \
                        + " tax rate: " + str(value['tax_rate']) + " tax_amount: " + str(value['tax_amount']) \
                        + " invoice_amount: " + str(value['invoice_amount']) \
                        )

    return tax

        
@frappe.whitelist()
def get_make_invoice(party_type, party, invoice_items_dict, transaction_ref=None \
                        , invoice_date=None, posting_date=None, cost_center=None ):
    # customer = doc.customer_record
    # invoice_items_dict contains the item code, amount and tax amount for all items on the invoice
    # invoice_items_dict{item_code1:{ 
    #                 'item':..,
    #                 'item_group':..,
    #                 'tax_account':..,
    #                 'tax_amount':..,
    #                 'invoice_amount':..,
    #                 'tot_tax_amount':..
    #             }
    #         }
    nowdate=frappe.utils.nowdate()
    if not invoice_date:
        invoice_date=nowdate

    if not posting_date:
        posting_date=nowdate

    company = frappe.db.get_default("Company")

    cost_center = cost_center if cost_center else frappe.db.get_value("Company", company, "cost_center", cache=True)
    # invoice_amount=tax[0].invoice_amount
    if party_type=='Customer':
        inv=frappe.new_doc('Sales Invoice')
        inv.customer = party
        inv.nexdha_reference=transaction_ref
        inv.set_posting_time=1
        inv.posting_date=invoice_date
        inv.due_date=invoice_date
        inv.company=company
        

        ###################ITERATING THROUGH THE INVOICE_ITEMS_DICT
        row_item=''
        item_tax=dict()
        total_tax_amount=0
        net_invoice_amount = 0
        for keys, item_lines in invoice_items_dict.items():
            for key, item_line in item_lines.items():
                # for k in tax_line.keys():
                #     frappe.msgprint(k)

                if row_item != item_line['item']:
                    row_item=item_line['item']
                    net_invoice_amount+=item_line['invoice_amount']
                    temp_item= frappe.get_cached_doc("Item", item_line['item'])
                    inv_amt = item_line['invoice_amount'] if item_line['invoice_amount'] else 0
                
                    # frappe.msgprint( 'item_code: '+ temp_item.item_code \
                    #                 + '\nrate: ' + str(item_line['invoice_amount']) \
                    #                 + '\nqty: ' + str(item_line['qty']) \
                    #                 + '\namount: ' + str(inv_amt) \
                    #                 + '\nuom: ' + temp_item.stock_uom \
                    #                 + '\ndescription : ' + "Transaction Type: " + temp_item.item_name \
                    #                 # + '\nincome_account: ' + str(temp_item.item_defaults[0].income_account) \
                    #                 + '\ngst_hsn_code: '+ temp_item.gst_hsn_code                    \
                    #                 + '\nitem_name: ' +temp_item.item_name \
                    #                 + '\nconversion_factor: ' + str(1) \
                    #                 + '\nbase_rate: ' + str(inv_amt) \
                    #                 + '\nbase_amount: ' +str(inv_amt) \
                    #                 + '\ncost_center: ' + cost_center \
                    #                 )

                    row = inv.append("items",
                                {
                                    'item_code':temp_item.item_code
                                    , 'rate': item_line['invoice_amount']
                                    , 'qty':item_line['qty']
                                    , 'amount':inv_amt
                                    , 'uom':temp_item.stock_uom
                                    , 'description': "Transaction Type: " + temp_item.item_name
                                    , 'income_account':temp_item.item_defaults[0].income_account
                                    , 'gst_hsn_code': temp_item.gst_hsn_code                    
                                    # , 'item_name':temp_item.item_name
                                    # , 'conversion_factor': 1
                                    # , 'base_rate':tax_line.invoice_amount
                                    # , 'base_amount': tax_line.invoice_amount
                                    # , 'cost_center': cost_center

                                })
                if item_line['tax_account'] in item_tax.keys():
                    item_tax[item_line['tax_account']]['tax_amount']+=item_line['tax_amount']
                else:
                    item_tax[item_line['tax_account']]= {   
                                                    'charge_type': 'On Net Total'
                                                    , 'account_head': item_line['tax_account']
                                                    , 'rate': item_line['tax_rate']*100
                                                    , 'tax_amount': item_line['tax_amount']
                                                }
        
        for key, item_tax_row in item_tax.items():
            total_tax_amount+=item_tax_row['tax_amount']
            row = inv.append("taxes",{
                                    'charge_type': item_tax_row['charge_type']
                                    , 'account_head':item_tax_row['account_head']
                                    , 'rate': item_tax_row['rate']
                                    , 'tax_amount': item_tax_row['tax_amount']
                                    , 'description': "Account Head: " + item_tax_row['account_head'] + "| @Rate: " + str(item_tax_row['rate']) + "%"
                            })
        
    
    # inv.base_grand_total = inv.base_rounded_total = inv.grand_total=inv.rounded_total=net_invoice_amount+total_tax_amount
    # inv.base_net_total = net_invoice_amount

    inv.remarks =   "<b>**Auto Generated Invoice** </b>" 

    
    # inv.save()
    try:
        if net_invoice_amount<=0:
            frappe.msgprint("Invoice Amount must be greater than Zero")
            return None
        inv.insert(ignore_permissions=True)
    except Exception as e:
        template = "When creating invoice for party: " + party + "| Tx Ref: " + transaction_ref + \
                    "an exception of type {0} occurred, arguments:\n{1!r}"
        message = template.format(type(e).__name__, e.args)
        frappe.throw(message)
        return None
    
    return inv









@frappe.whitelist()
def get_make_jv(doc=None,  type=None):
    # return
    if not doc or not type:
        return
    
    sType1 = 'transaction_initiation_jv'
    sType2 = 'settlement_into_nodal_jv'
    sType3 = 'beneficiary_settlement_jv'
    nodal_account = frappe.get_cached_doc('Mode of Payment',doc.payment_gateway_setup.pg_payment_mode).accounts[0].default_account

    jv = frappe.new_doc('Journal Entry')
    jv.company=doc.company
    #customer sales amount and tax details NOT USED IN JV
    # for item_tax_sales_details in doc.customer_item_tax.items():
    #     for tax_line in item_tax_sales_details.items():
    #
    #Supplier sales amount and tax details
    row_item= ''
    item_tax= 0
    net_invoice_amount = 0
    for key, item_tax_purchase_details in doc.supplier_items_dict.items():
        for key1, tax_line in item_tax_purchase_details.items():
            if row_item != tax_line['item']:
                net_invoice_amount += tax_line['invoice_amount']
                row_item=tax_line['item']
            
            item_tax += tax_line['tax_amount']
    # frappe.msgprint("Clearance Entry. Inv_amt: " + str(net_invoice_amount) + "| item_tax" + str(item_tax))
    supplier_invoice_amount = net_invoice_amount+item_tax

    ##############################INITIAL CLEARANCE ENTRY#################################
    if type == sType1:
        if doc.transaction_initiation_jv:
            return frappe.get_cached_doc("Journal Entry",doc.transaction_initiation_jv)
         
        

        jv.posting_date = doc.transaction_date
        jv.mode_of_payment = doc.payment_gateway_setup.pg_payment_mode
        jv.cheque_no = doc.transaction_reference_number
        jv.cheque_date = doc.transaction_date
        jv.user_remark =    "<b>"+sType1 + " :(Clearance Account Entry): </b> "                   #Automatically generated jv created on " + str(frappe.utils.formatdate(frappe.utils.nowdate())) \
        
        #   rounding_diff = round(doc.charged_amount,2)-round(doc.supplier_tax[0]['invoice_amount'],2) - round((doc.charged_amount - doc.supplier_tax[0]['invoice_amount']),2)
        
        
        # Journal Entry#1
        ##1 Credit Customer: 102.5 | Amount charged to the card
        ##2 Debit Payment Gateway: 1.18 (if 1% fees) | this is the amount charged by PG to Nexhda. Nodal account gets the balance after deduction
        ##3 Debit Clearance Account: 101.32 | balance gets into clearance account, for reconciliation post settlement by PG
        # 
        # Customer Credit Entry for total amount charged to card
        # frappe.msgprint(sType1 + ": charged_amt: " + str(doc.charged_amount) + " | supplier_invoice_amount: " + str(supplier_invoice_amount))
        row = jv.append("accounts",
                    {
                        
                        'party_type': 'Customer'
                        , 'party': doc.customer_record
                        , 'account': doc.pg_transaction_defaults.customer_clearance_account
                        , 'debit_in_account_currency': 0
                        , 'credit_in_account_currency':doc.charged_amount
                        
                    }
                )

        # PG Fees Debit Entry - supplier fee payment is captured here, as an advance. PG deducts fee before settling. 
        # iF fees is Zero, this entry is not needed. eg UPI
        if supplier_invoice_amount>0:
            row = jv.append("accounts",
                        {
                            
                            'party_type': 'Supplier'
                            , 'party': doc.payment_gateway_setup.payment_gateway_supplier
                            , 'account': get_party_account('Supplier',doc.payment_gateway_setup.payment_gateway_supplier, doc.company)
                            , 'debit_in_account_currency': supplier_invoice_amount
                            , 'credit_in_account_currency':0
                            , 'is_advance': 'Yes'
                        }
                    )
        # Clearance Account Entry
        row = jv.append("accounts",
                    {
                        'account': doc.payment_gateway_setup.settlement_clearance_account
                        , 'debit_in_account_currency': doc.charged_amount - supplier_invoice_amount
                        , 'credit_in_account_currency':0
                    }
                )
    
    ##############################SETTLEMENT TO NODAL #################################
    elif type == sType2:
        if doc.settlement_into_nodal_jv:
            return frappe.get_cached_doc("Journal Entry", doc.settlement_into_nodal_jv)

        transaction_date= frappe.utils.getdate(doc.transaction_date) 
        for row in doc.payment_gateway_setup.payment_gateway_settlement_rates:
                if row.active and (doc.pg_service_type_item_code == row.service_item) \
                        and row.rate_active_from <= transaction_date <= row.rate_active_to :
                    pg_settlement_days = row.settlement_days
                    break

        jv.posting_date = transaction_date
        jv.mode_of_payment = doc.payment_gateway_setup.pg_payment_mode
        jv.cheque_no = doc.transaction_reference_number
        jv.cheque_date = find_next_working_day(transaction_date, pg_settlement_days)
        jv.user_remark =     "<b>" + sType2 + " :(Settlement to Nodal): </b> "                   #Automatically generated jv created on " + str(frappe.utils.formatdate(frappe.utils.nowdate())) 
        ## Settlement into nodal account
        amount_settled_into_nodal = doc.charged_amount - supplier_invoice_amount

        # frappe.msgprint(sType2 + ": Nodal Amt: " + str(amount_settled_into_nodal) \
        #                 + " cheque_date: " + str(jv.cheque_date) \
        #                 + " pg Settlement days" + str(pg_settlement_days) \
        #                 + " posting_date: " + str(transaction_date) )

        row = jv.append("accounts",
                    {
                        
                        'account': nodal_account
                        , 'debit_in_account_currency': amount_settled_into_nodal
                        , 'credit_in_account_currency':0
                    }
                )
        # Clearance Account Entry
        row = jv.append("accounts",
                    {
                        'account': doc.payment_gateway_setup.settlement_clearance_account
                        , 'debit_in_account_currency': 0
                        , 'credit_in_account_currency':amount_settled_into_nodal
                    }
                )

    
    ##SETTLEMENT TO CUSTOMER & RECOGNITION OF PAYMENT TO NEXDHA JV #########
    elif type == sType3:
        if doc.beneficiary_settlement_jv:
            return frappe.get_cached_doc("Journal Entry", doc.beneficiary_settlement_jv)

        
        jv.posting_date = doc.eta
        jv.mode_of_payment = doc.payment_gateway_setup.pg_payment_mode
        jv.cheque_no = doc.transaction_reference_number 
        jv.cheque_date = doc.eta
        jv.user_remark =     "<b>"+sType3 + " :(Settlement to Beneficiary): </b> "
        # Payment from nodal account (Credit settled_amount)
        # frappe.msgprint(sType3 + ": Settled_amt: " + str(doc.settled_amount) + " | charged_amount: " + str(doc.charged_amount) )
        row = jv.append("accounts",
                    {
                        
                        'account': nodal_account
                        , 'debit_in_account_currency': 0
                        , 'credit_in_account_currency':doc.settled_amount
                    }
                )
        # recognition of advance received from customer (credit payable)
        if doc.charged_amount-doc.settled_amount > 0:
            row = jv.append("accounts",
                        {
                            'party_type': 'Customer'
                            , 'party': doc.customer_record
                            , 'account': get_party_account(party_type='Customer',party=doc.customer_record,company= doc.company)
                            , 'debit_in_account_currency': 0
                            , 'credit_in_account_currency': doc.charged_amount - doc.settled_amount
                            , 'is_advance': 'Yes'
                        }
                    )
        # reversal of total outstanding amount on customer clearance account
        row = jv.append("accounts",
                    {
                        'party_type': 'Customer'
                        , 'party': doc.customer_record
                        , 'account': doc.pg_transaction_defaults.customer_clearance_account
                        , 'debit_in_account_currency': doc.charged_amount
                        , 'credit_in_account_currency':0
                    }
                )

    #############################################################RETURN JV#####################

    try:
        jv.insert(ignore_permissions=True)
    except Exception as e:
        template = "During creation of JV : " + type  + "|" + doc.transaction_reference_number + ", an exception of type {0}  occured with arguments:\n{1!r} "
        message = template.format(type(e).__name__, e.args)
        frappe.throw(message)
        return

    return jv


@frappe.whitelist()
def get_make_customer(pg_tran=None,  add_if_missing=False):
    # check if the Nexdha_user_id has already been created in the DB. 
    cust=c=None
    c = frappe.db.get_value("Customer", {"nexdha_user_id": pg_tran.nexdha_user_id }, "name", cache=True)
    if c:
        cust = frappe.get_cached_doc('Customer', c)
        # print("C:" + c.customer_name)
        return cust
    elif not add_if_missing:
        return None
    
    ###########################ADD NEW CUSTOMER
    company = pg_tran.company
    
    # default_tax_category = 
    
    cust_state = frappe.db.get_value("States And Provinces",{"state_province_name": pg_tran.customer_state}, "state_province_name", cache=True) or \
                 frappe.db.get_value("States And Provinces",{"abbrev": pg_tran.customer_state}, "state_province_name", cache=True) or \
                 frappe.db.get_value("States And Provinces",{"alias": pg_tran.customer_state}, "state_province_name", cache=True) or \
                 pg_tran.default_gst_state
    
    # frappe.msgprint("Cust_State: " + cust_state + " | Default State:" + default_state)
    
    cust = frappe.new_doc('Customer')

    cust.customer_name=pg_tran.customer_name
    cust.nexdha_user_id=pg_tran.nexdha_user_id
    cust.customer_type = 'Company' if pg_tran.customer_gst else 'Individual' #hardcoded. need to improve logic!
    cust.customer_group = pg_tran.pg_transaction_defaults.default_customer_group
    
    cust.tax_category = pg_tran.pg_transaction_defaults.local_customer_tax_category \
                        if cust_state == pg_tran.default_gst_state else pg_tran.pg_transaction_defaults.interstate_customer_tax_category

    cust.gst_category = 'Registered Regular' if pg_tran.customer_gst else 'Unregistered'
    
    try:
        cust.insert(ignore_permissions=True)
    except Exception as e:
        template = "During creation of customer : " + pg_tran.customer_name  + "|" + pg_tran.transaction_reference_number + ", an exception of type {0}  occured with arguments:\n{1!r} "
        message = template.format(type(e).__name__, e.args)
        frappe.throw(message)
        return {}

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
    
    try:
        cust_addr.insert(ignore_permissions=True)
    except Exception as e:
        template = "During creation of customer address for : " + pg_tran.customer_name  + "|" + pg_tran.transaction_reference_number + ", an exception of type {0}  occured with arguments:\n{1!r} "
        message = template.format(type(e).__name__, e.args)
        frappe.throw(message)
        return {}
        

    return cust

    


@frappe.whitelist()
def delete_nexdha_cc2casa_transaction(doc, method=None):
    
    ref_docs=get_tx_docs(doc,True)

    doc.transaction_initiation_jv=None
    doc.settlement_into_nodal_jv=None
    doc.beneficiary_settlement_jv=None
    doc.customer_invoice=None
    
    try:
        for key, row in ref_docs.items():
            if not row['doc']:
                continue
            if row['doc'].docstatus==1:
                if row['doctype']=='Sales Invoice': 
                    #Delete any payment reconciliation and reload
                    frappe.db.delete('Sales Invoice Advance',{
                                            'parenttype': 'Sales Invoice'
                                            , 'parent': row['doc'].name
                                        })
                    row['doc'].reload()

                row['doc'].cancel()
                # row['doc'].reload()
                frappe.msgprint("CANCELLED " + row['doc'].name)


            frappe.delete_doc(row['doctype'], row['doc'].name, force=1, for_reload=True)
            frappe.msgprint("DELETED " + row['doc'].name)

    except Exception as e:
        frappe.msgprint(str(e))
        frappe.msgprint(str(frappe.DoesNotExistError))
        if "KeyError" == type(e).__name__:
            pass
        else:
            template = "Function: Delete_nexdha_cc2casa_transaction. Documents for : " + doc.customer_name  + "|" + doc.transaction_reference_number + ", an exception of type {0}  occured with arguments:\n{1!r} "
            message = template.format(type(e).__name__, e.args)
            frappe.throw(message)
            return


    
        
#when cancelling a CC2CASA transaction - delete all of the related documents!
@frappe.whitelist()
def cancel_nexdha_cc2casa_transaction(doc, method=None):    
    delete_nexdha_cc2casa_transaction(doc, method)
    date = frappe.utils.nowdate()
    doc.transaction_reference_number= "CAN-" + frappe.utils.formatdate(date,"yyyy-MM-dd") +"-" + doc.transaction_reference_number


@frappe.whitelist()
def get_tx_docs( pg_tran,  get_docs=False):
    ref_docs={}
    ref_docs[0]={'doctype':'Journal Entry', 'name':pg_tran.transaction_initiation_jv, 'submit': pg_tran.submit_transaction_initiation_jv}
    ref_docs[1]={'doctype':'Journal Entry', 'name':pg_tran.settlement_into_nodal_jv, 'submit': pg_tran.submit_settlement_into_nodal_jv}
    ref_docs[2]={'doctype':'Journal Entry', 'name':pg_tran.beneficiary_settlement_jv, 'submit': pg_tran.submit_beneficiary_settlement_jv}
    ref_docs[3]={'doctype':'Sales Invoice', 'name':pg_tran.customer_invoice, 'submit': pg_tran.submit_customer_invoice}
    
    if get_docs:
        try:
            for key, doc_link in ref_docs.items():
                if doc_link['name']:
                    # frappe.msgprint("GET_TX_DOCS: " + doc_link['doctype'])
                    doc_link['doc']=frappe.get_doc(doc_link['doctype'], doc_link['name'])

        except frappe.DoesNotExistError:
            doc_link['doc']=None
            # frappe.msgprint("did not find"+ str(doc_link['name']))
            pass

    
    return ref_docs



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