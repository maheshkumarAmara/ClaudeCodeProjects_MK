"""Opportunity Header checks, ported from the Opportunity validation rules in the QA org. No Streamlit.

Each check reads the Opportunity as it is saved on the Order and asks whether the rule's
requirement holds for the Opportunity's current stage. The org rules are gated on ISCHANGED()
and only fire on a save that changes the field. A saved record cannot show that, so these are
state checks: they say what a save into that stage would require.

Opportunity header vs line-item sync (SAL25-145, OpportunityObjectTriggerHelper.validateOppHeaderAndLinesSync)
is an Apex trigger check, not a validation rule. It is ported as a state check too. The org gates it on the
Disable_Opp_Manual_Arroyo_values_Sync_validation label being "No" (it is "No" in QA); this port assumes it is on.

Not ported:
- Profile and business-group exemptions (System Administrator, Rubrik Data Migration Admin,
  Rubrik Product Manager, Deal Operations, Business Group RD/RVP/AVP/GVP). These depend on the
  user who saves the record, not on the record itself.
- Cloud_Enviromment (needs OrderItem product counts).
- Stage 6 PDF Addendum, Trade-Up hold and Click-Thru rules (need Contact Role and trade-up data).
"""

from decimal import Decimal, ROUND_HALF_UP

from ov.calc import fmt_amount

POS_SUB_TYPE = "POS Opportunity"  # $Label.POS_Opportunity in QA

STAGE_2 = "2 Consensus"
STAGE_3 = "3 Technical Validation"
STAGE_4 = "4 Business Justification"
STAGE_5 = "5 Negotiate & Close"
STAGE_6 = "6 PO With Channel"
STAGE_7_WON = "7 Closed Won"
STAGE_7_LOST = "7 Closed Lost"

STAGES_FROM_2 = {STAGE_2, STAGE_3, STAGE_4, STAGE_5, STAGE_6, STAGE_7_WON}
STAGES_FROM_3 = {STAGE_3, STAGE_4, STAGE_5, STAGE_6, STAGE_7_WON}
STAGES_FROM_4 = {STAGE_4, STAGE_5, STAGE_6, STAGE_7_WON}
STAGES_FROM_5 = {STAGE_5, STAGE_6, STAGE_7_WON}

SLED_INDUSTRIES = {
    "Education", "State Government", "Local Government", "Government", "Education - K-12",
    "Education - Higher Ed", "Special District", "K-12 Schools", "Local", "State",
}
PARTNER_PROFILES = {
    "Partner Community User", "Rubrik Partner Community Manager", "Rubrik Partner Community User",
}
STAGE3_REQUIRED_FIELDS = [
    ("Metric__c", "Metric"),
    ("Economic_Buyer__c", "Economic Buyer"),
    ("Decision_Criteria__c", "Decision Criteria"),
    ("Decision_Process__c", "Decision Process"),
    ("Why_Rubrik__c", "Why Rubrik"),
    ("Why_do_anything__c", "Why do anything"),
    ("Why_now__c", "Why now"),
]


# (Opportunity header field, OpportunityLineItem field, label) — one row per sum in validateOppHeaderAndLinesSync.
# The first entry (ACV) is summed with the Renewal / non-Renewal line filter; the rest are plain sums.
HEADER_LINE_SYNC_FIELDS = [
    ("ACV_Amount__c", "ACV_Amount__c", "ACV Amount"),
    ("Renewal_Subsumed_ACV__c", "Subsumed_Renewal_Amount__c", "Renewal Subsumed ACV"),
    ("Subsumed_Renewal_TCV__c", "Subsumed_Renewal_TCV__c", "Subsumed Renewal TCV"),
    ("New_Expansion_ACV__c", "New_Expansion_ACV__c", "New Expansion ACV"),
    ("New_Expansion_TCV__c", "New_Expansion_TCV__c", "New Expansion TCV"),
    ("Core_New_Expansion_ACV__c", "Core_New_Expansion_ACV__c", "Core New Expansion ACV"),
    ("Nas_New_Expansion_ACV__c", "Nas_New_Expansion_ACV__c", "NAS New Expansion ACV"),
    ("SaaS_New_Expansion_ACV__c", "SaaS_New_Expansion_ACV__c", "SaaS New Expansion ACV"),
    ("PLS_NCD_New_Expansion_ACV__c", "PLS_NCD_New_Expansion_ACV__c", "PLS NCD New Expansion ACV"),
    ("Subsumed_Renewal_Churn_ACV__c", "Subsumed_Renewal_Churn_ACV__c", "Subsumed Renewal Churn ACV"),
    ("Subsumed_Renewal_Churn_TCV__c", "Subsumed_Renewal_Churn_TCV__c", "Subsumed Renewal Churn TCV"),
    ("Comp_Uplift_ACV__c", "Comp_Uplift_ACV__c", "Comp Uplift ACV"),
]
SYNC_ERROR_MSG = ("An opportunity amount override needs to be reviewed/updated. "
                  "Please contact dealgovernance@rubrik.com for assistance.")


def _scale2(value):
    """Apex Decimal.setScale(2): HALF_UP rounding to 2 decimals."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def header_line_sync_mismatches(opp: dict, line_items: list) -> list:
    """Return [(label, header_value, line_total)] for each header field that differs from its line-item sum."""
    is_renewal_opp = opp.get("Opportunity_Sub_Type__c") == "Renewal"
    mismatches = []
    for header_field, line_field, label in HEADER_LINE_SYNC_FIELDS:
        total = Decimal("0")
        for line in line_items:
            value = line.get(line_field)
            if value is None:
                continue
            if header_field == "ACV_Amount__c":
                is_renewal_line = line.get("Line_Type__c") == "Renewal"
                if is_renewal_opp != is_renewal_line:
                    continue
            total += Decimal(str(value))
        header = opp.get(header_field)
        if header is None:
            differs = total != 0
        else:
            differs = _scale2(header) != _scale2(total)
        if differs:
            mismatches.append((label, header, total))
    return mismatches


def _blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def _shown(value):
    return "(blank)" if _blank(value) else str(value)


def _money(value):
    return fmt_amount(value) if value is not None else "(blank)"


def _row(name, applies, violated, error_msg, details, expected, actual):
    if not applies:
        status = "ℹ️ N/A — rule not triggered for this stage or type"
    elif violated:
        status = f"❌ FAIL — {error_msg}"
    else:
        status = "✅ PASS"
    return {"#": "—", "Validation": name, "Details": details,
            "Expected": expected, "Actual": actual, "Status": status}


def opp_header_checks(order_record: dict, opp_line_items=None) -> list:
    """Return the Opportunity Header rows for one Order record (the dict from the Order SOQL).

    opp_line_items is the list of OpportunityLineItem records for the Opportunity (the Q11 query). When it is
    None the header-vs-line-sync check is reported as N/A.
    """
    opp = order_record.get("Opportunity") or {}
    if not opp:
        return [{"#": "—", "Validation": "Opportunity Header",
                 "Details": "No Opportunity linked to this Order (OpportunityId is blank).",
                 "Expected": "—", "Actual": "(blank)", "Status": "ℹ️ N/A — no Opportunity"}]

    stage = opp.get("StageName") or ""
    sub_type = opp.get("Opportunity_Sub_Type__c") or ""
    opp_type = opp.get("Opportunity_Type__c") or ""
    rt_dev = (opp.get("RecordType") or {}).get("DeveloperName") or ""
    amount = opp.get("Amount")
    amount_150k = amount is not None and amount >= 150000
    is_pos = sub_type == POS_SUB_TYPE
    is_debook = opp_type == "Debooking"
    is_split = not _blank(opp.get("Opportunity_Split_Parent__c"))
    is_child_renewal = sub_type == "Renewal" and bool(opp.get("Is_child_Renewal_split__c"))
    is_sales_rt = rt_dev == "Sales_Opportunity"
    primary_quote = opp.get("SBQQ__PrimaryQuote__r") or {}
    contact = opp.get("Initial_Contacts_Name__r") or {}
    account = opp.get("Account") or {}
    polaris = bool(opp.get("Has_Polaris_Product__c")) or bool(opp.get("PolarisDetailsRequired__c"))
    aspen_values = [v.strip() for v in (opp.get("Aspen_Eligibility__c") or "").split(";")]
    rows = []

    # Amount_on_Opp_and_Quote_Mismatch — Stage 6: Opportunity.Amount must equal primary quote net amount
    quote_net = primary_quote.get("SBQQ__NetAmount__c")
    rows.append(_row(
        "Amount matches Primary Quote Net Amount",
        applies=stage == STAGE_6 and not is_pos and amount is not None and bool(primary_quote)
                and opp.get("split__c") is not True,
        violated=amount is not None and quote_net is not None
                 and round(float(amount), 4) != round(float(quote_net), 4),
        error_msg="The Opportunity Amount and Quote Amount do not match. Please uncheck and then re-check "
                  "the Primary checkbox on the primary quote to re-sync the quote with the opportunity.",
        details=f"Stage: {stage or '(blank)'} | Opportunity.Amount: {_money(amount)} | "
                f"Primary Quote Net Amount: {_money(quote_net)}",
        expected=_money(quote_net), actual=_money(amount),
    ))

    # CM_is_required_to_move_to_Stage_6 — Actual Aspen deals need a Contract Manufacturer at Stage 6
    cm = opp.get("ContractManufacturer__c")
    rows.append(_row(
        "Contract Manufacturer required for Actual Aspen at Stage 6",
        applies=stage == STAGE_6 and not is_pos and "Actual Aspen" in aspen_values
                and not opp.get("Override__c"),
        violated=_blank(cm),
        error_msg="Contract Manufacturer should have value to move Opportunity's Stage to 6 PO With Channel",
        details=f"Aspen Eligibility: {_shown(opp.get('Aspen_Eligibility__c'))} | "
                f"Override: {bool(opp.get('Override__c'))} | Contract Manufacturer: {_shown(cm)}",
        expected="Contract Manufacturer populated", actual=_shown(cm),
    ))

    # Champion_is_required — Amount >= $150k (non-renewal) needs a Champion
    champion = opp.get("Champion__c")
    rows.append(_row(
        "Champion required (Amount >= $150k, non-renewal)",
        applies=stage in STAGES_FROM_2 and amount_150k
                and sub_type not in ("Renewal", "MSP Overage", "GC OnDemand")
                and not is_pos and not is_debook,
        violated=_blank(champion),
        error_msg="Champion is required field for Amount > $150k for non renewal Opportunity.",
        details=f"Stage: {stage or '(blank)'} | Amount: {_money(amount)} | Champion: {_shown(champion)}",
        expected="Champion populated", actual=_shown(champion),
    ))

    # Cloud_Type_is_required — Stage 6 / 7 Won
    cloud_type = opp.get("Cloud_Type__c")
    rows.append(_row(
        "Cloud Type required at Stage 6 / 7 Won",
        applies=stage in {STAGE_6, STAGE_7_WON} and not is_debook and sub_type != "MSP Overage"
                and not is_pos and not is_child_renewal,
        violated=_blank(cloud_type),
        error_msg="Cloud Type is required field .",
        details=f"Stage: {stage or '(blank)'} | Cloud Type: {_shown(cloud_type)}",
        expected="Cloud Type populated", actual=_shown(cloud_type),
    ))

    # Forward_Pass_Contact_is_Required — Forward Pass > 0 needs a contact name and email
    forward_pass = opp.get("Forward_Pass__c") or 0
    fp_contact = opp.get("Forward_Pass_Contact__c")
    fp_mail = opp.get("Forward_Pass_Contact_Mail__c")
    rows.append(_row(
        "Forward Pass contact required",
        applies=(stage in {STAGE_6, STAGE_7_WON}
                 or (stage == STAGE_7_LOST and opp.get("Lost_Reason__c") != "Duplicate Opp"))
                and forward_pass > 0 and sub_type != "MSP Overage" and not is_pos and not is_debook,
        violated=_blank(fp_contact) or _blank(fp_mail),
        error_msg="Forward Pass Contact Name & Email are Required",
        details=f"Forward Pass: {forward_pass} | Contact: {_shown(fp_contact)} | Email: {_shown(fp_mail)}",
        expected="Contact name and email populated", actual=f"{_shown(fp_contact)} / {_shown(fp_mail)}",
    ))

    # Override_true_if_Primary_Quote_is_Aspen — Aspen override conflicts with an Aspen primary quote
    process_type = primary_quote.get("ProcessType__c") or ""
    rows.append(_row(
        "Aspen override conflicts with Aspen primary quote",
        applies=stage == STAGE_6 and not is_pos and process_type == "Aspen",
        violated=bool(opp.get("Override__c")),
        error_msg="Conflict alert. The opportunity has the Aspen override checked, but the primary Quote in Aspen. "
                  "To resolve, uncheck the Aspen override field (to make the deal Aspen) or generate a new "
                  "standard quote (to make the deal non-Aspen)",
        details=f"Primary Quote ProcessType: {_shown(process_type)} | Override: {bool(opp.get('Override__c'))}",
        expected="Override__c = false", actual=f"Override__c = {bool(opp.get('Override__c'))}",
    ))

    # Polaris_Portal_Contact_Mandatory — RSC products need a Rubrik Security Cloud Owner at Stage 5+
    portal_contact = opp.get("Polaris_Portal_Contact__c")
    rows.append(_row(
        "RSC Owner (Polaris Portal Contact) required",
        applies=stage in STAGES_FROM_5 and polaris and not is_debook and not is_pos
                and sub_type != "MSP Overage",
        violated=_blank(portal_contact),
        error_msg="This Opportunity has Polaris Product. Please populate “Rubrik Security Cloud Owner” to Proceed.",
        details=f"Has Polaris Product / Details Required: {polaris} | Polaris Portal Contact: {_shown(portal_contact)}",
        expected="Polaris Portal Contact populated", actual=_shown(portal_contact),
    ))

    # Polaris_Region_Req_for_Opp_Stage_5_Or_6 — RSC products need a region at Stage 5 or 6
    polaris_region = opp.get("Polaris_Region__c")
    rows.append(_row(
        "RSC Region required (Stage 5 / 6)",
        applies=stage in {STAGE_5, STAGE_6} and polaris and not is_debook and not is_pos
                and sub_type not in ("MSP Overage", "GC OnDemand"),
        violated=_blank(polaris_region),
        error_msg="RSC Region is required if Opportunity has RSC Product(s) or RSC Details Required fields are checked.",
        details=f"Has Polaris Product / Details Required: {polaris} | Polaris Region: {_shown(polaris_region)}",
        expected="Polaris Region populated", actual=_shown(polaris_region),
    ))

    # Primary_Competitor_Required_at_Stage_3 — the org formula's Stage 6 literal is '6 PO with Channel'
    # (lowercase "with"). ISPICKVAL is case-sensitive, so that clause never matches and Stage 6 is not
    # enforced by this rule. Stage 6 is left out here to match.
    primary_competitor = opp.get("Primary_Competitor__c")
    rows.append(_row(
        "Primary Competitor required (Stage 3+)",
        applies=stage in {STAGE_3, STAGE_4, STAGE_5, STAGE_7_WON} and not is_debook and not is_pos,
        violated=_blank(primary_competitor),
        error_msg='"Primary Competitor" must be filled in to advance. Please update Opportunity record.',
        details=f"Stage: {stage or '(blank)'} | Primary Competitor: {_shown(primary_competitor)}",
        expected="Primary Competitor populated", actual=_shown(primary_competitor),
    ))

    # Primary_Contact_is_Required — contact must belong to the Account, have an email, and not be a partner user
    init_contact = opp.get("Initial_Contacts_Name__c")
    contact_profile = contact.get("User_Profile__c") or ""
    contact_bad = (_blank(init_contact) or contact.get("AccountId") != opp.get("AccountId")
                   or _blank(contact.get("Email")) or contact_profile in PARTNER_PROFILES)
    rows.append(_row(
        "Primary Contact on the Account with a valid email",
        applies=stage in STAGES_FROM_4 and not is_debook and not is_pos and sub_type != "MSP Overage",
        violated=contact_bad,
        error_msg="Please select a Primary Contact that is from the same Account as this Opportunity. If Contact "
                  "does not exist create a new Contact for this Account and link it as the Primary Contact. "
                  "Primary Contacts must also have a valid email address.",
        details=f"Primary Contact: {_shown(contact.get('Name'))} | Contact Account match: "
                f"{contact.get('AccountId') == opp.get('AccountId')} | Email: {_shown(contact.get('Email'))} | "
                f"Profile: {_shown(contact_profile)}",
        expected="Contact on Opportunity Account, with email, not a partner user",
        actual=_shown(init_contact),
    ))

    # Rubrik_Contract_field_required — State/National Coop Contract for SLED accounts (NY always)
    state = (account.get("BillingStateCode") or "").upper()
    contract = opp.get("Rubrik_Contract__c")
    sled_outside_ny = (state != "NY" and account.get("BillingCountry") == "United States"
                       and account.get("ETM_Area__c") in ("AMER-SLED-1", "AMER-SLED-2")
                       and account.get("Industry") in SLED_INDUSTRIES)
    rows.append(_row(
        "State / National Coop Contract required (SLED and NY)",
        applies=stage == STAGE_6 and not is_debook and not is_pos and sub_type != "MSP Overage",
        violated=_blank(contract) and (sled_outside_ny or state == "NY"),
        error_msg="State/National Coop Contract can not be blank",
        details=f"Billing State: {_shown(state)} | Country: {_shown(account.get('BillingCountry'))} | "
                f"ETM Area: {_shown(account.get('ETM_Area__c'))} | Industry: {_shown(account.get('Industry'))} | "
                f"Contract: {_shown(contract)}",
        expected="Rubrik Contract populated", actual=_shown(contract),
    ))

    # Win_Notes_Required_to_Close_Won — Stage 6 / 7 Won need Win/Loss notes (not on Renewal record types)
    win_notes = opp.get("Win_Loss_Comments__c")
    rows.append(_row(
        "Win Notes required (Stage 6 / 7 Won)",
        applies=stage in {STAGE_6, STAGE_7_WON} and not is_debook and not is_pos
                and rt_dev != "Renewal_Opportunity",
        violated=_blank(win_notes),
        error_msg="You must include Win Notes in order to Continue",
        details=f"Stage: {stage or '(blank)'} | Win/Loss Comments: {_shown(win_notes)}",
        expected="Win/Loss Comments populated", actual=_shown(win_notes),
    ))

    # Stage3_required_Fields — Amount >= $150k, non-sales record types: 7 qualification fields
    missing_qual = [label for fld, label in STAGE3_REQUIRED_FIELDS if _blank(opp.get(fld))]
    rows.append(_row(
        "Qualification fields required (Amount >= $150k, non-Sales record type)",
        applies=stage in STAGES_FROM_3 and amount_150k and sub_type != "Renewal" and not is_split
                and not is_sales_rt,
        violated=bool(missing_qual),
        error_msg="Metric, Economic Buyer, Decision Criteria, Decision Process, Why Rubrik, Why do anything, "
                  "and Why now are required fields for Amount > $150k for non renewal Opp.",
        details=f"Stage: {stage or '(blank)'} | Missing: {', '.join(missing_qual) or 'none'}",
        expected="All 7 qualification fields populated", actual=f"{len(missing_qual)} missing",
    ))

    # Stage3_required_Fields_For_Sales_Oppty — Amount >= $150k, Sales record type: Economic Buyer
    economic_buyer = opp.get("Economic_Buyer__c")
    rows.append(_row(
        "Economic Buyer required (Amount >= $150k, Sales record type)",
        applies=stage in STAGES_FROM_3 and amount_150k and sub_type != "Renewal" and not is_split
                and is_sales_rt and not is_pos,
        violated=_blank(economic_buyer),
        error_msg="Economic Buyer is required fields for Amount > $150k for non renewal Opportunity.",
        details=f"Stage: {stage or '(blank)'} | Economic Buyer: {_shown(economic_buyer)}",
        expected="Economic Buyer populated", actual=_shown(economic_buyer),
    ))

    # Validate_Scale_Cloud_Percentage — Stage 6 Sales deals with a Scale Cloud % need SE Director validation
    scale_validated = opp.get("Scale_Cloud_Validated__c")
    rows.append(_row(
        "Scale Cloud % validated (Stage 6, Sales record type)",
        applies=stage == STAGE_6 and is_sales_rt and not is_debook and not is_pos
                and sub_type != "MSP Overage" and opp.get("UCL_Scale_Percentage__c") is not None,
        violated=not scale_validated,
        error_msg="Please work with your SE Director (or above) to validate Scale Cloud %",
        details=f"UCL Scale %: {_shown(opp.get('UCL_Scale_Percentage__c'))} | "
                f"Scale Cloud Validated: {bool(scale_validated)}",
        expected="Scale Cloud Validated = true", actual=f"{bool(scale_validated)}",
    ))

    # SAL25-145 — Opportunity header amounts must equal the sum of the line items when an amount override is on
    override = bool(opp.get("Opportunity_Amount_Override__c"))
    if opp_line_items is None:
        sync_mismatches = []
        sync_details = "Opportunity line items were not fetched."
    else:
        sync_mismatches = header_line_sync_mismatches(opp, opp_line_items)
        sync_details = (f"Amount Override: {override} | Line items: {len(opp_line_items)} | "
                        + ("all 12 header fields match line totals" if not sync_mismatches else
                           "; ".join(f"{label}: header {_money(h)} vs lines {_money(t)}"
                                     for label, h, t in sync_mismatches)))
    rows.append(_row(
        "Header amounts match Opportunity Line Items (Amount Override)",
        applies=opp_line_items is not None and override and stage in (STAGE_6, STAGE_7_WON),
        violated=bool(sync_mismatches),
        error_msg=SYNC_ERROR_MSG,
        details=f"Stage: {stage or '(blank)'} | {sync_details}",
        expected="Header = sum of line items (2 dp) for all 12 fields",
        actual="In sync" if not sync_mismatches else f"{len(sync_mismatches)} field(s) differ",
    ))

    return rows
