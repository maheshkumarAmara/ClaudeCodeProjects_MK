---
name: sfdc-qa-quote-reset
description: >-
  Reset a Quote in a Salesforce (SFDC) QA or UAT sandbox back to a clean,
  re-sellable state. Use when the user gives a QuoteNumber or OrderNumber and an
  environment (Env: QA or UAT) and wants all downstream records (other quotes,
  orders, booking records, service contracts, entitlements, linked assets)
  removed so only the initial quote remains and acts like a new sale.
  QA/UAT sandboxes only - never production.
---

# SFDC QA/UAT Quote Reset

Given an environment (QA or UAT) and a QuoteNumber or OrderNumber, find it in that
SFDC sandbox, delete everything created downstream of the initial Quote, and leave
that Quote clean so it can be sold again.

## Steps

1. **Get the input.** The user provides:
   - **Env:** `QA` or `UAT` (for example "Env: UAT, Quote Q-00123")
   - **A QuoteNumber or an OrderNumber**

   If Env is missing, ask which environment (QA or UAT). Never assume one. If Env
   is anything else (Prod, Production, Dev, etc.), refuse and explain that only
   QA and UAT are supported. If the number is missing, ask for it. If several
   numbers are given, process them one at a time.

2. **Safety check - org must match the requested Env.** Before anything else,
   query the `Organization` object (`Name`, `IsSandbox`, `InstanceName`).
   - If `IsSandbox = false`, STOP. Tell the user the connected org is production
     and that nothing will be searched for deletion or changed. Explain that the
     connector must be pointed at the requested sandbox first.
   - If `IsSandbox = true`, confirm it is the sandbox the user asked for. Check
     what the org gives you (for example the sandbox suffix on the current
     user's username, or the instance name). If you cannot verify that it is QA
     (or UAT, as requested), ask the user to confirm before continuing.
   - If the connected sandbox is clearly the other environment (asked for UAT but
     connected to QA, or the reverse), STOP and tell the user. Do not switch or
     continue on the wrong environment.

3. **Find the record.**
   - QuoteNumber: query the Quote object by `QuoteNumber`.
   - OrderNumber: query the Order object by `OrderNumber`, then trace back to the
     Quote it came from.
   - If nothing is found, say so and ask the user to double-check the number.
     Do not guess or search loosely.

4. **Identify the initial Quote.** Look at all Quotes in the same chain (same
   Opportunity / Account relationship, or linked through revisions and
   amendments). The initial Quote is the earliest created one, unless the user
   says otherwise. If it is ambiguous, show the candidates and ask.

5. **Discover object names.** Booking records and some other objects may be
   custom. Use `salesforce_search_objects` and `salesforce_describe_object` to
   find the real API names and the relationship fields. Do not assume names.

6. **Find everything related.** Collect, for the whole chain:
   - Other Quotes (everything except the initial Quote)
   - Orders and order items
   - Booking records
   - Service contracts (and contract line items)
   - Entitlements
   - Linked assets
   Use read-only queries. Count records per object.

7. **PREVIEW AND APPROVAL (required checkpoint).** Show:
   - The Env requested, plus the org name and instance (to prove it matches)
   - The Quote being KEPT (number, Id, status)
   - A table of records to DELETE: object, count, and record Ids/numbers
   Then ask: "Delete these records? Reply yes to proceed." Do nothing destructive
   until the user clearly says yes. Approval applies only to the list shown. If
   anything changes, show a new preview.

8. **Delete or hand off.**
   - If a write-enabled Salesforce tool for the requested Env is available in this session, delete
     in dependency order (children first): assets, entitlements, service
     contracts, booking records, orders, extra quotes.
   - If only read-only tools are available (the default), do NOT attempt to
     delete. Instead produce the exact delete list (CSV of Object, Id) and a
     ready-to-run script (Salesforce CLI `sf data delete record` or
     `sf data delete bulk`) in the same dependency order, and tell the user to
     run it in the requested Env.

9. **Clean the initial Quote.** The Quote should behave like a new sale:
   - Status back to Draft (or the org's initial status)
   - Clear lookups pointing at deleted orders, contracts, or bookings
   - Clear any "synced", "ordered", or "booked" flags and related dates
   Describe the exact field changes in the preview, and apply them (or include
   them in the script) only after approval. Confirm field names through
   `salesforce_describe_object` first.

10. **Report back.** Summarize what was deleted (counts per object), what was
    kept, and the final state of the Quote. Re-query to verify when possible.

## Output Format

    Env: <QA|UAT>
    Org: <Name> (<InstanceName>) - Sandbox: true

    KEEP
    - Quote <QuoteNumber> (<Id>) - Status: <status>

    DELETE
    | Object              | Count | Records            |
    |---------------------|-------|--------------------|
    | Asset               | 3     | <ids>              |
    | Entitlement         | 2     | <ids>              |
    | ServiceContract     | 1     | <ids>              |
    | <Booking object>    | 2     | <ids>              |
    | Order               | 2     | <numbers>          |
    | Quote (others)      | 1     | <numbers>          |

    QUOTE CLEANUP
    - Status: <old> -> Draft
    - <field>: <old> -> <new>

    Delete these records in <QA|UAT>? Reply yes to proceed.

## Rules

- QA and UAT sandboxes only. Never run against production or any other
  environment. If `IsSandbox = false`, stop.
- The Env the user names must match the connected org. Never run on a
  different environment than the one requested.
- Never delete without an explicit "yes" from the user after seeing the preview.
- Never delete the initial Quote.
- Only delete records connected to the chain you identified. Do not delete by
  broad filters such as "all orders for this account" without showing them first.
- Do not assume object or field names; confirm them in the org.
- Delete children before parents to avoid dependency errors.
- If a step fails or counts do not match the preview, stop and report instead of
  retrying blindly.
- Deletions may be hard to undo. Remind the user once, in the preview, that
  deleted records go to the Recycle Bin only where Salesforce allows it.
