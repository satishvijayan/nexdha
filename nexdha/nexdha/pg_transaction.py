# https://frappeframework.com/docs/user/en/basics/doctypes/controllers
# https://frappeframework.com/docs/user/en/python-api/hooks

# https://discuss.erpnext.com/t/when-to-use-hook-event/51532/3
# https://discuss.erpnext.com/t/on-submit-method-of-doctype/25178/2
# https://frappeframework.com/docs/user/en/python-api/hooks
# https://discuss.erpnext.com/t/api-erpnext-setup-utils-get-exchange-rate-unable-to-find-exchange-rate/29914
# https://about.lovia.life/docs/infrastructure/erpnext/erpnext-custom-doctypes-actions-and-links/
# https://discuss.erpnext.com/t/database-transaction-in-api-method/49091/6
# https://stackoverflow.com/questions/61331968/setting-a-value-in-frappe-application-isnt-reflected-in-erpnext-gui/61414160#61414160
# https://discuss.erpnext.com/t/help-needed-with-custom-script/25195
# https://discuss.erpnext.com/t/how-to-insert-child-table-records-link-to-existing-parent-table-row/25825/2
# https://discuss.erpnext.com/t/redirecting-to-new-doc/25980/7
#  https://discuss.erpnext.com/t/erpnext-v12-3-1-new-doctype-doctype-action-doctype-link-child-table/56659/6
#  https://about.lovia.life/docs/infrastructure/erpnext/erpnext-custom-doctypes-actions-and-links/
#  https://discuss.erpnext.com/t/tutorial-add-custom-action-button-custom-menu-button-custom-icon-button-in-form-view/45260
#  https://discuss.erpnext.com/t/add-custom-button-in-child-table/47405/4
#  https://github.com/frappe/frappe/wiki/Developer-Cheatsheet
#  https://discuss.erpnext.com/t/how-create-and-insert-a-new-document-through-custom-script/39158/6
#  https://discuss.erpnext.com/t/get-singles-value-in-js/18389/4
#  https://programtalk.com/python-examples/frappe.db.get_default/
#  https://discuss.erpnext.com/t/client-side-doc-creation-posting-date/49243/3
#  https://discuss.erpnext.com/t/redirecting-to-new-doc/25980/4
# https://discuss.erpnext.com/t/map-frappe-model-mapper-get-mapped-doc-doctype-with-other-s-doctype-child-table/29556/3
# https://discuss.erpnext.com/t/how-to-fetch-child-tables/12348/31
# https://github.com/frappe/frappe/blob/develop/frappe/email/doctype/auto_email_report/auto_email_report.py
# https://discuss.erpnext.com/t/list-of-client-side-javascript-events/35337/4
# https://discuss.erpnext.com/t/how-to-trigger-custom-script-after-importing-data/72482/4
# https://github.com/frappe/erpnext/wiki/Community-Developed-Custom-Scripts
# https://discuss.erpnext.com/t/how-to-import-a-js-module-in-frappe/50589/2
# https://discuss.erpnext.com/t/how-to-automatically-update-issue-status-to-replied-after-sending-email/33018/8
# https://discuss.erpnext.com/t/import-function-from-external-library/10896
# https://github.com/frappe/frappe/blob/develop/frappe/core/doctype/server_script/server_script_utils.py#L6
# https://discuss.erpnext.com/t/custom-name-attribute-for-customers/41649/5

from __future__ import unicode_literals
import frappe, math
from frappe import _
from frappe.utils import flt
from frappe.model.mapper import get_mapped_doc
from frappe.model.document import Document

def wrapstring(s):
    return '"' + str(s) + '"' if s else  ''

@frappe.whitelist()
def submit_nexdha_cc2casa_transaction(doc, method):
    stx_doctype='Nexdha CC2CASA Transaction'
    spg_setup_doctype='Payment Gateway Setup'

    # if not doc.name:
    #     return {}
    # # doc_name = wrapstring(doc_name)
    # # print(doc_name)
    
    # if not frappe.db.exists("Nexdha CC2CASA Transaction", doc_name):
    #     # print("doctype: " + doc_name + "does not exist")
    #     return{}

    # pg_tran = frappe.get_doc("Nexdha CC2CASA Transaction",   doc_name)
    # frappe.msgprint(pg_tran.name)

    pg_tran=doc
    # customer_location=pg_tran.customer_location
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
    payment_gateway =frappe.get_doc(spg_setup_doctype, pg_tran.payment_gateway)
    pg_commission_percent =pg_tran.pg_commission_percent
    # submit_transaction_initiation_jv =pg_tran.submit_transaction_initiation_jv
    # submit_settlement_into_nodal_jv = pg_tran.submit_settlement_into_nodal_jv
    # submit_beneficiary_settlement_jv = pg_tran.submit_beneficiary_settlement_jv
    # submit_customer_invoice = pg_tran.submit_customer_invoice
    # customer_record = pg_tran.customer_record
    # customer_invoice = pg_tran.customer_invoice
    # transaction_initiation_jv= pg_tran.transaction_initiation_jv
    # settlement_into_nodal_jv = pg_tran.settlement_into_nodal_jv
    # beneficiary_settlement_jv = pg_tran.beneficiary_settlement_jv
    
    
    
    if pg_commission_percent:
        pg_reference_rate=pg_commission_percent
    else:
        for row in payment_gateway.payment_gateway_settlement_rates:
                if row.active and row.rate_active_from <= transaction_date <= row.active_to:
                    pg_reference_rate=row.pg_reference_rate
                    break

    doc.customer_record = get_customer(pg_tran=pg_tran,add_if_missing=True ).name
    # frappe.msgprint(doc.customer_record)
    # doc.save(ignore_permissions=True)

    transaction_initiation_jv=None
    settlement_into_nodal_jv=None
    beneficiary_settlement_jv=None
    sales_invoice=None
    # return frappe._dict({
    #     'customer': customer.name
    #     # 'transaction_initiation_jv': transaction_initiation_jv.name,
    #     # 'settlement_into_nodal_jv': settlement_into_nodal_jv.name,
    #     # 'beneficiary_settlement_jv':beneficiary_settlement_jv.name,
    #     # 'customer_invoice': sales_invoice.name
    # })




@frappe.whitelist()
def get_customer(pg_tran=None,  add_if_missing=False):
    # check if the Nexdha_user_id has already been created in the DB. 
    cust=c=None
    c = frappe.db.get_value("Customer", {"nexdha_user_id": pg_tran.nexdha_user_id }, "name")
    if c:
        cust = frappe.get_doc('Customer', c)
        # frappe.msgprint("C:" + c.customer_name)
    
    elif add_if_missing:
        company = pg_tran.company
        default_state = frappe.db.get_value('PG Transactions Defaults',{'company': company}, 'default_gst_state') 
        default_tax_category = frappe.db.get_value('PG Transactions Defaults', {'company':company}, 'default_customer_tax_category') 
        
        cust = frappe.new_doc('Customer')

        cust.customer_name=pg_tran.customer_name
        cust.nexdha_user_id=pg_tran.nexdha_user_id
        cust.customer_type= frappe.db.get_value('PG Transactions Defaults',{'company':company}, 'default_customer_type')
        cust.customer_group = frappe.db.get_value('PG Transactions Defaults',{'company':company}, 'default_customer_group')
        cust.tax_category = default_tax_category
        cust.insert(ignore_permissions=True)

        
        
        cust_addr = frappe.new_doc('Address')
        cust_addr.address_title = cust.nexdha_user_id
        cust_addr.address_line1 = default_state
        cust_addr.gst_state = default_state
        cust_addr.tax_category = default_tax_category
        cust_addr.city = default_state
        cust_addr.phone=pg_tran.customer_phone

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

def name_customer(doc, method):
    if doc.nexdha_user_id:
        # doc.name = "CUST-FROM-MYAPP-{}".format(doc.my_own_id)
        doc.name="EXT-" + str(doc.nexdha_user_id)