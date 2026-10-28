"""Salesforce access through the sf CLI (no Streamlit, safe to call from worker threads)."""

import concurrent.futures
import json
import subprocess

def verify_sf_org(alias: str):
    """Verify alias is known to SF CLI; returns (username, instance_url) or ('', '')."""
    for cmd in (["sf", "org", "display", "--target-org", alias, "--json"],
                ["sfdx", "force:org:display", "--targetusername", alias, "--json"]):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            data = json.loads(proc.stdout)
            result = data.get("result", {})
            username = result.get("username", "")
            if username:
                return username, result.get("instanceUrl", "")
        except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired):
            continue
    return "", ""


def run_sf_query(alias: str, soql: str) -> dict:
    """Execute SOQL via SF CLI — the CLI handles token refresh automatically."""
    soql_clean = " ".join(soql.split())
    last_err   = "SF CLI query failed — is `sf` (or `sfdx`) CLI installed?"
    for cmd in (["sf", "data", "query", "--query", soql_clean, "--target-org", alias, "--json"],
                ["sfdx", "force:data:soql:query", "--query", soql_clean, "--targetusername", alias, "--json"]):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            data = json.loads(proc.stdout)
            if data.get("status") == 0:
                r = data.get("result", {})
                return {"totalSize": r.get("totalSize", 0), "records": r.get("records", [])}
            last_err = data.get("message", str(data))
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        except json.JSONDecodeError:
            continue
    raise Exception(last_err)


def _prefetch_order_data(order_num: str, alias: str) -> dict:
    """Pre-fetch all SF data for one order — 5 concurrent SOQL queries (down from 3+2 sequential)."""

    # ── Q1: Order header + all line items in one round-trip (child subquery) ──
    soql_combined = f"""
        SELECT Id, OrderNumber, AccountId, Manufacturing_Integration_Partner__c,
               ProcessType__c, Manual_Fulfilment_Selection_Reason__c,
               SBQQ__Contracted__c, SC_or_Entitlement_Stage__c,
               Stage_PO__c, ScreenStatus__c, Est_Ship_Date__c,
               Deliver_By__c, Order_Accepted_Timestamp__c,
               CreatedBy.Name, Auto_Manual_Booked__c,
               customer_required_ship_date__c, Type, Order_Sub_Type__c,
               Line_Types__c, BookingStatus__c, Order_Status__c,
               Have_Polaris_Products__c,
               Opportunity.Has_Polaris_Product__c,
               Opportunity.RecordType.DeveloperName,
               Opportunity.Rubrik_Security_Cloud_Gov_t_Owner__c,
               Opportunity.Rubrik_Security_Cloud_Gov_t_Owner__r.Email,
               Opportunity.Rubrik_Security_Cloud_Gov_t_Owner__r.Phone,
               Opportunity.Amount, Opportunity.SBQQ__Ordered__c,
               Opportunity.Account.RCDMT_EOL_Date__c,
               Has_Third_Party_Hardware_Product__c,
               Third_Party_Hardware_fulfilment_status__c,
               RSC_G_Enabled__c, Ready_for_Gov_Sync__c,
               RSC_G_Contact__c, RSC_G_Contact_Email__c, RSC_G_Contact_Phone__c,
               Bill_To_Name__r.Id, Bill_To_Name__r.Name,
               TotalAmount,
               SBQQ__Quote__r.Id, SBQQ__Quote__r.Name,
               SBQQ__Quote__r.ProcessType__c, SBQQ__Quote__r.SBQQ__NetAmount__c,
               SBQQ__Quote__r.Manual_Fulfillment_Quote__c,
               SBQQ__Quote__r.SBQQ__Status__c, SBQQ__Quote__r.ApprovalStatus__c,
               SBQQ__Quote__r.SBQQ__Type__c, SBQQ__Quote__r.SBQQ__Primary__c,
               SBQQ__Quote__r.SBQQ__Ordered__c, SBQQ__Quote__r.SBQQ__ContractingMethod__c,
               SBQQ__Quote__r.SBQQ__PaymentTerms__c,
               SBQQ__Quote__r.SBQQ__StartDate__c, SBQQ__Quote__r.SBQQ__EndDate__c,
               SBQQ__Quote__r.SBQQ__ExpirationDate__c, SBQQ__Quote__r.SBQQ__SubscriptionTerm__c,
               SBQQ__Quote__r.SBQQ__ListAmount__c, SBQQ__Quote__r.SBQQ__CustomerAmount__c,
               SBQQ__Quote__r.SBQQ__RegularAmount__c, SBQQ__Quote__r.SBQQ__AdditionalDiscountAmount__c,
               SBQQ__Quote__r.SBQQ__PricebookId__c, SBQQ__Quote__r.Commit_Type__c,
               SBQQ__Quote__r.RCDMT_EOL_Date__c, SBQQ__Quote__r.Is_Quote_Amount_Equal_to_Oppty_Amount__c,
               SBQQ__Quote__r.Skip_Theatre_Approval_Step__c, SBQQ__Quote__r.MetricCalcStatus__c,
               SBQQ__Quote__r.TotalACV__c, SBQQ__Quote__r.RTA__c,
               SBQQ__Quote__r.OpportunitySubType__c,
               ManualFulfilment__c, Actual_Order_Ship_Date__c,
               Welcome_letter_sent_for_the_first_time__c,
               WelcomeEmailSentforSoftwareProducts__c, SD_Status__c,
               Primary_Contact_Screen_Status__c, Shipping_Carrier__c, SCAC__c, Smart_Hands_Provider__c,
               SBQQ__PriceCalcStatus__c, Have_Hardware_Products__c, Polaris_Fulfillment_Status__c,
               Order_Split_Type__c, POC_Opportunity__c, POC_Completion_Date__c, POC_Type__c,
               POC_Opportunity__r.Distributor_Lookup__c, POC_Opportunity__r.Distributor_Lookup__r.Name,
               (SELECT Product2.Shipping_Lead_Time__c, Product2.Order_Fulfilment__c, Product2.Name,
                       SBQQSC__ContractLineItem__c,
                       Printable_Product__c, Opportunity_Product__r.Printable_Product__c,
                       Payment_Options__c, SBQQ__QuoteLine__r.Product_Payment_Option__c,
                       SBQQ__SubscriptionTerm__c, SBQQ__QuoteLine__r.SBQQ__SubscriptionTerm__c,
                       SBQQ__QuoteLine__r.SBQQ__StartDate__c, SBQQ__QuoteLine__r.SBQQ__EndDate__c,
                       SBQQ__QuoteLine__r.End_Date__c,
                       SerialNumber__c, Upgraded_From__c,
                       Support_Start_Date__c, Support_End_Date__c,
                       Support_Term__c, Segment_Label__c, Quarter__c,
                       SBQQ__QuoteLine__r.SBQQ__SegmentLabel__c, Product2.Product_Type__c,
                       SBQQ__QuoteLine__r.Subscribed_Asset_Name__c,
                       SBQQ__QuoteLine__r.SubscribedAssetNames__c,
                       SBQQ__QuoteLine__r.Arroyo_Subscribed_Asset_Name__c,
                       UnitPrice, Quantity, TotalPrice, Sales_Price__c,
                       SBQQ__QuoteLine__r.SBQQ__NetPrice__c,
                       Previous_Transaction_Reference__c, Replacement_Type__c, Credit_Amount__c,
                       Product_Name__c,
                       SBQQ__OrderedQuantity__c, ServiceDate, EndDate,
                       Actual_Sales_Price__c, Entitlement_Id__c,
                       SBQQ__QuoteLine__r.SBQQ__ListPrice__c, SBQQ__QuoteLine__r.SBQQ__CustomerPrice__c,
                       SBQQ__QuoteLine__r.SBQQ__Product__r.Upgrade_Path__c,
                       SBQQ__QuoteLine__r.Account_s_Entitlement__c,
                       SBQQ__QuoteLine__r.Prepayment_Credit__c, SBQQ__QuoteLine__r.SBQQ__Quantity__c,
                       TPH_Drive_Size__c, TPH_Models_Gen__c, TPH_OEM__c, TPH_Quantity__c,
                       SBQQ__QuoteLine__r.TPH_Drive_Size__c, SBQQ__QuoteLine__r.TPH_Models_Gen__c,
                       SBQQ__QuoteLine__r.TPH_OEM__c, SBQQ__QuoteLine__r.TPH_Quantity__c,
                       Previous_Contract_Line__c, Previous_Contract_Line_Items__c,
                       SBQQ__QuoteLine__r.Arroyo_Subsumed_Old_Contract_Line_Items__c,
                       SBQQ__QuoteLine__r.SBQQSC__RenewedContractLine__c,
                       SBQQ__QuoteLine__r.SBQQ__Quote__r.SBQQ__Type__c,
                       RBOB_ACV__c, Renewal_Target_Amount_ACV__c, PromoDiscTCV__c, Oppty_Trade_Up_Discount__c,
                       Opportunity_Product__c,
                       Opportunity_Product__r.Quantity, Opportunity_Product__r.RBOBACV__c,
                       Opportunity_Product__r.Renewal_Target_Amount__c,
                       Opportunity_Product__r.PromoDiscTCV__c, Opportunity_Product__r.Oppty_Trade_Up_Discount__c,
                       SBQQ__RequiredBy__c, Has_PSTask__c, Task_Created__c,
                       Global_Commit_ID__c, Global_Commit_Split_ID__c, SBQQ__Contracted__c,
                       Licence_Type__c, Cluster_Order_Type__c, Program__c, Additional_Term__c,
                       Surviving_Amount__c, Trade_Up_SerialNumber__c,
                       Buyer_Part_Number__c, EDI_Line_Number__c, SBQQ__QuoteLine__c
                FROM OrderItems)
        FROM Order WHERE OrderNumber = '{order_num}' LIMIT 1
    """

    # ── Q2: Order Success Metrics ─────────────────────────────────────────────
    soql_metrics = f"""
        SELECT Order_Creation_Metrics__c, Order_Booking_Metrics__c,
               Order_Provisioning_Metrics__c, Booking_Creation_Metrics__c,
               SC_creation_Metrics__c, Stage_PO_Submission_Metrics__c,
               CLI_creation_Metrics__c, Entitlement_Creation_Metrics__c, Comment__c
        FROM Order_Success_Metrics__c
        WHERE Order__r.Order_Number__c = '{order_num}' LIMIT 1
    """

    # ── Q3: Entitlements — pre-fetched in parallel to avoid a sequential round-trip ──
    soql_ent = f"""
        SELECT Name, Type, SubType__c,
               Order_Service_Item__r.Printable_Product__c,
               Product__r.Name,
               Order_Service_Item__r.Product2.Name,
               Subscription_Term__c,
               Order_Service_Item__r.SBQQ__SubscriptionTerm__c,
               Order_Service_Item__r.Support_Term__c,
               Quantity__c, Order_Quantity__c,
               AccountId, Manufacturing_Integration_Partner__c,
               Order_Service_Item__c, StartDate, EndDate
        FROM Entitlement
        WHERE Order_Service_Item__r.Order.Order_Number__c = '{order_num}'
    """

    # ── Q4: Scale_Entitlement__c — linked-asset field-consistency validation ──
    soql_scale_ent = f"""
        SELECT Name, Type__c, Sub_Type__c, Renewal_Category__c, Status__c,
               Asset__c, Asset__r.SBQQSC__RequiredByLineItem__c,
               Entitlement__c, Entitlement__r.Name, Entitlement__r.Type,
               Entitlement__r.ContractLineItemId,
               Contract_Line_Item__c, Order_Product__c
        FROM Scale_Entitlement__c
        WHERE Order_Product__r.Order.Order_Number__c = '{order_num}'
    """

    # ── Q5: ContractLineItem — field-consistency validation against source OrderItem ──
    soql_cli = f"""
        SELECT Id, SBQQSC__OrderProduct__c, ServiceContractId,
               Product2Id, Product2.Name,
               Quantity, StartDate, EndDate,
               Product_Type__c, Product_Subtype__c,
               Required_by_Product_Code__c,
               SBQQSC__OrderProduct__r.Quantity,
               SBQQSC__OrderProduct__r.ServiceDate,
               SBQQSC__OrderProduct__r.EndDate,
               SBQQSC__OrderProduct__r.Product2Id,
               SBQQSC__OrderProduct__r.SBQQ__SubscriptionTerm__c,
               Contract_End_Date__c, Subscription_Term__c,
               SBQQSC__Product__c,
               Product2.Family, Product2.Product_Level__c, Product2.TPH_Models_Gen__c, Product2.Third_party_SKU_DRIVE_Size__c,
               Product2.Product_Subtype__c, Product2.License_Category__c,
               TPH_OEM__c, TPH_Models_Gen__c, TPH_Drive_Size__c, TPH_Quantity__c,
               SBQQSC__QuoteLine__c,
               SBQQSC__QuoteLine__r.POT_Parent_Source__c, SBQQSC__QuoteLine__r.POT_Parent_List_Price__c,
               SBQQSC__QuoteLine__r.Product_Level__c, SBQQSC__QuoteLine__r.Product_Type__c, SBQQSC__QuoteLine__r.Product_Subtype__c,
               SBQQSC__QuoteLine__r.SBQQ__Optional__c,
               SBQQSC__QuoteLine__r.SBQQSC__RenewedContractLine__c, SBQQSC__QuoteLine__r.SBQQSC__RenewedContractLine__r.AMER_FED_Exception__c,
               SBQQSC__QuoteLine__r.RWD_Deal_Ops_Exception__c,
               SBQQSC__QuoteLine__r.Scale_Utility_Product_Identifier__c,
               POT_Parent_Source__c, POT_Parent_List_Price__c, AMER_FED_Exception__c,
               Global_Commit_ID__c, Max_Commit__c, SBQQSC__TerminatedDate__c, SBQQSC__SegmentQuantity__c,
               SBQQSC__RenewalQuantity__c, Resync_Line__c
        FROM ContractLineItem
        WHERE SBQQSC__OrderProduct__r.Order.Order_Number__c = '{order_num}'
    """

    # ── Q6: OrderHistory — feeds Order_Success_Metrics recomputation ───────────
    soql_order_history = f"""
        SELECT OrderId, CreatedDate, CreatedBy.Name, Field, NewValue
        FROM OrderHistory
        WHERE Order.OrderNumber = '{order_num}'
        AND Field IN ('BookingStatus__c','Order_Status__c','Polaris_Fulfillment_Status__c')
        ORDER BY CreatedDate ASC
    """

    # ── Q7: ServiceContract — earliest-created SC for this order ───────────────
    soql_service_contract = f"""
        SELECT Id, SBQQSC__Order__c, CreatedDate
        FROM ServiceContract
        WHERE SBQQSC__Order__r.OrderNumber = '{order_num}'
        ORDER BY CreatedDate ASC LIMIT 1
    """

    # ── Q8: OrderItem gate — mirrors Apex orderProductOrderSet/CLI/Entitlement maps ──
    soql_order_item_gate = f"""
        SELECT Id, SBQQSC__ContractLineItem__c, OrderId,
               (SELECT Order_Service_Item__c FROM Entitlements__r WHERE Type = 'Phone Support')
        FROM OrderItem
        WHERE Order.Order_Status__c = 'Shipped'
        AND PricebookEntry.Product2.SBQQSC__EntitlementConversion__c != null
        AND Order.SBQQ__Quote__c != NULL
        AND Order.Type = 'Revenue'
        AND Order.OrderNumber = '{order_num}'
    """

    # ── Q9: Order_control__mdt — automation-user allowlist + thresholds ────────
    soql_order_control_mdt = """
        SELECT DeveloperName, Value__c
        FROM Order_control__mdt
        WHERE DeveloperName IN ('OrderAPIUser','OrderAutomationUser','PolarisAPIUser',
                                'OrderShipBookedTimeDiff','OrderSCCLIEntitlementTimeDiff')
    """

    # ── Q10: SBQQ__QuoteLine__c — QuoteLines tab validations ────────────────────
    # Semi-join on Order.OrderNumber (rather than needing the Quote Id up front)
    # so this can run in the same parallel round as every other query here.
    soql_quote_lines = f"""
        SELECT Id, Name, SBQQ__Number__c, SBQQ__Product__r.Name, SBQQ__ProductCode__c,
               SBQQ__Quantity__c, SBQQ__ListPrice__c, SBQQ__RegularPrice__c,
               SBQQ__CustomerPrice__c, SBQQ__NetPrice__c, SBQQ__Discount__c,
               SBQQ__AdditionalDiscount__c, SBQQ__PartnerDiscount__c, SBQQ__SpecialPrice__c,
               SBQQ__PricingMethod__c, SBQQ__EffectiveQuantity__c,
               SBQQ__ChargeType__c, SBQQ__SubscriptionTerm__c, SBQQ__StartDate__c, SBQQ__EndDate__c,
               SBQQ__Bundle__c, SBQQ__BundledQuantity__c, SBQQ__RequiredBy__c, SBQQ__ProductOption__c,
               SBQQ__Product__r.SBQQ__SubscriptionPricing__c, SBQQ__Product__r.SBQQ__PricingMethod__c
        FROM SBQQ__QuoteLine__c
        WHERE SBQQ__Quote__c IN (SELECT SBQQ__Quote__c FROM Order WHERE OrderNumber = '{order_num}')
        ORDER BY SBQQ__Number__c ASC
    """

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as _pool:
        _fc = _pool.submit(run_sf_query, alias, soql_combined)
        _fm = _pool.submit(run_sf_query, alias, soql_metrics)
        _fe = _pool.submit(run_sf_query, alias, soql_ent)
        _fse = _pool.submit(run_sf_query, alias, soql_scale_ent)
        _fcli = _pool.submit(run_sf_query, alias, soql_cli)
        _fh = _pool.submit(run_sf_query, alias, soql_order_history)
        _fsc = _pool.submit(run_sf_query, alias, soql_service_contract)
        _fog = _pool.submit(run_sf_query, alias, soql_order_item_gate)
        _fmdt = _pool.submit(run_sf_query, alias, soql_order_control_mdt)
        _fql = _pool.submit(run_sf_query, alias, soql_quote_lines)
        _combined = _fc.result()
        _metrics  = _fm.result()
        _ent      = _fe.result()
        _scale_ent = _fse.result()
        _cli      = _fcli.result()
        _history  = _fh.result()
        _sc       = _fsc.result()
        _orderitem_gate = _fog.result()
        _mdt      = _fmdt.result()
        _ql       = _fql.result()

    # Flatten OrderItems subquery into the same dict structure the caller expects
    _order_rec = (_combined.get("records") or [{}])[0]
    _items_sub = _order_rec.get("OrderItems") or {}
    _items = {
        "records":   _items_sub.get("records")   or [],
        "totalSize": _items_sub.get("totalSize") or 0,
        "done":      _items_sub.get("done", True),
    }

    return {
        "result":          _combined,
        "items_result":    _items,
        "metrics_result":  _metrics,
        "ent_result":      _ent,
        "scale_ent_result": _scale_ent,
        "cli_result":      _cli,
        "history_result":  _history,
        "sc_result":       _sc,
        "orderitem_gate_result": _orderitem_gate,
        "mdt_result":      _mdt,
        "ql_result":       _ql,
    }
