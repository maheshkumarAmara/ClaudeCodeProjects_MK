# PO Processing Engine

Upload an existing PO (Purchase Order) PDF, edit fields in the browser, and download a regenerated PDF with the updated values.

## Status

Working end-to-end for the distributors listed in the Distributors table below: load the template PDF into an editable form (`GET /api/distributors/{slug}/template`), edit fields and line items, and download a regenerated PDF (`POST /api/distributors/{slug}/generate`). Line items are fully dynamic (add/remove/reorder rows) with true multi-page reflow when the items table overflows the first page. PDF editing uses `pypdf` + `reportlab` (whiteout-and-redraw overlay merged onto the original template page) rather than PyMuPDF, to avoid its AGPL/commercial licensing.

Known limitations:
- Replacement text is drawn in Helvetica at the original point size rather than the original embedded subset font — visually close, not pixel-identical.
- Only one real 2-page sample PO was available for `arrow-ecs-sau` and for `exclusive-networks-south-africa`, so synthesized continuation/trailer pages (beyond what the sample PDF itself contains) reuse that sample's page backgrounds; this should be revisited if a genuinely longer real PO from either distributor turns up.
- `NextGen Distribution Pty Ltd` has its own parser and generator (`pdf_engine/parsers/nextgen_distribution_pty_ltd.py`, `pdf_engine/generator_nextgen_distribution_pty_ltd.py`) instead of a `DistributorLayout`. Preview/Generate paginate the items across pages with their section headings ("Expansion Quote" / "Renewal Quote"), redraw the header, address blocks, footer terms and "Order Total" bar, and renumber "Page No. N of M". The Term Qty / Term / Start / End columns are read from each row's `terms` text (e.g. `18 Months (2/01/2026 - 30/06/2027)`; a bare number means months). A loaded row keeps its printed amount until its qty, unit price or terms are edited; after that (and for rows pulled from a Quote) it is recomputed as qty × unit price × term months. The Order Total is always the sum of the rows, so it can differ from the sample's own printed total (the sample's rows add up to 684,617.50 against a printed 684,613.43). "Use this Quote" fills line items plus four header fields: `delivery_name` and `end_user` (both the Quote's Account Name, `SBQQ__Account__c`), `quote_number` (the Quote Name) and `total` (the Quote's `SBQQ__NetAmount__c`, written as `USD <amount>`). No other NextGen header fields have a Salesforce mapping yet. Note the PDF's Order Total bar is still computed from the line items — `total` only supplies its currency code — so the printed total can differ from the Quote's Net Amount when the pulled lines exclude renewals, optional lines or RBK/RHA/RCA products.
- `Computer Gross spa` has its own parser and generator (`pdf_engine/parsers/computer_gross_spa.py`, `pdf_engine/generator_computer_gross_spa.py`). Its template is a one-page form with a 12-row items table, but the generator builds the table itself, so a PO can have any number of line items. A PO of up to 12 lines prints exactly the template's 12-row page (unused rows blank). More lines grow the table in place while the TOTAL / Shipping / IOR block still fits on the page; beyond that the table continues on extra pages that repeat the column header, and the TOTAL / Shipping / IOR block and closing sentence go on the last page only (each page of a multi-page PO is labelled "PO <number> - Page i of n"). The closing sentence ("... ACCEPTS ALL ADDITIONAL TERMS ON RUBRIK QUOTE <quote> DATED <date>") is rebuilt from `quote_number` and `quote_date`. Clickable `mailto:` links are rebuilt to match the printed addresses (the template's own links are dropped). The TOTAL is the sum of qty × unit price over the rows. Limits: the pieces of the template page that aren't shown (unused rows, the old header/tail values) stay in the PDF's hidden text layer, so copy/paste or text search of the PDF can still find the sample PO's original values, including its original email addresses; descriptions are clipped to their cell width; text is Helvetica, not the template's Tahoma.
- `Exclusive Networks (Norway)` has its own parser and generator (`pdf_engine/parsers/exclusive_networks_norway.py`, `pdf_engine/generator_exclusive_networks_norway.py`). The template is a flowing 2-page document with no ruled table; the generator cuts the letterhead/header, the repeated column-header band, the totals block and the footer out of the template pages and places them around rows it draws itself, so a PO can have any number of line items (pages are added as needed, the header band repeats, and the totals block goes under the last row — never under an empty table). Every number is recomputed: a row's Net Amount is qty × Disc. U.P (U.P less any "% disc."), the subtotal is the sum of the rows, tax is the subtotal × the `tax_rate` field and the total is subtotal + tax; the printed subtotal/tax/total form fields are not used. A row's Quote ID is its own `quote_id`, else the form's `quote_number`, else the quote number in the comment line (the comment line's quote number is swapped to match when a different `quote_number` is supplied). A bare `terms` number (as pulled from Salesforce) prints as "Terms N months". A row carrying `serial_number` / `contract_start_date` / `contract_end_date` prints the "Supported S/N / Contract Start / End Date" block above it (the parser attaches each block in the sample to the row printed below it — a judgement call, as the PDF doesn't say which row a block belongs to); the form has no columns for those three values, so they only appear for a row loaded from the template. The footer's static "Email:" line and the template's `mailto:` links are rebuilt on `sandbox.com`. Long SKUs wrap mid-token instead of overflowing. Pulling a Quote fills only the line items: there is no Salesforce field mapper for this distributor yet, and the default mapper's `quote_number` / `buyer` keys don't exist on this form, so no header fields are filled. Limits: text is Helvetica, not the template's Noto Sans; the original text of covered or clipped-away template pieces stays in the PDF's hidden text layer (the generated PDF's extracted text contains each such value more than once, so don't rely on text extraction of it); months aren't pluralized ("Terms 1 months").
- Distributors with a dedicated parser and generator (see the Distributors table below): ADN, Arrow (Netherlands), Computer Gross, Exclusive Networks (Norway), Ingram Micro Canada, Innocom, Networld, NextGen and NOX. Only `arrow-ecs-sau` and `exclusive-networks-south-africa` use a `DistributorLayout` (see `pdf_engine/layouts/`); their sample PDFs now sit in `data/templates/Old/` and they are hidden from the dropdown. Every other slug in `config.DISTRIBUTORS` (including `iValue InfoSolutions Limited` and `HCL America, Inc.`, which are still listed) returns a "not yet configured" or "no template" error from the template/generate endpoints until a parser/generator or layout and sample PDF are added.
- For `exclusive-networks-south-africa`, long `part_number`/`description` values are wrapped onto extra lines (word-wrap for description, character-wrap for part numbers, mirroring how the sample PDF itself wraps a long code mid-character) to fit their table columns; row height and the "Terms:" line position adjust automatically to whichever column wraps taller. Most of the page-1 info panel (dispatch instructions, "Ship to"/contact block, billing address) is static distributor boilerplate left as untouched background — only the order-specific lines (Quote #, reseller/end user, PO number, contact, address, shipment/payment terms) are modeled as editable fields.

## Salesforce integration (pull-only)

The "Pull from Salesforce" panel lets you search a Salesforce CPQ Quote by name and pre-fill the edit form instead of typing everything by hand. It's a **read-only pull** — nothing is ever written back to Salesforce.

- `GET /api/salesforce/orgs` — lists the selectable org aliases (`config.SALESFORCE_ORGS`) and the default.
- `GET /api/salesforce/quotes/search?q=<term>&org=<alias>` — searches `SBQQ__Quote__c.Name` via `LIKE '%term%'` against the given org.
- `GET /api/salesforce/quotes/{quote_id}/data?org=<alias>` — runs a fixed `SBQQ__QuoteLine__c` query scoped to that Quote (excluding renewals, optional lines, and RBK/RHA/RCA product families) and maps it to fields/line items.

An **Org** dropdown next to the search box lets you pick which authenticated org to query — QA (`rbkqa`) or UAT (`uat-org`) — at runtime, no restart needed. Every search/pull result message states which org it came from. The `org` value is validated server-side against `config.SALESFORCE_ORGS`; unknown values get a 400.

Requirements:
- The [Salesforce CLI](https://developer.salesforce.com/tools/salesforcecli) (`sf`) must be installed and already authenticated to each selectable org alias (`sf org list`) on the machine running the server. No in-app Salesforce login flow exists.
- `config.SALESFORCE_ORGS` (alias → display label) defines the dropdown's choices; add an entry there for any additional authenticated org. `SALESFORCE_ORG_ALIAS` in `.env` sets which one is selected by default (defaults to `rbkqa`).

Known limitations:
- `% disc.` has no source field in the underlying query — always left blank for manual entry, for every distributor.
- The fields populated from a Quote pull are distributor-specific (the `sf_mapper` set on each entry in `distributors.py`), since each distributor's PDF layout models its fields differently:
  - `arrow-ecs-sau`: `quote_number` (Quote Name) and `buyer` (Account Name).
  - `exclusive-networks-south-africa`: this layout bakes each field's static label into the same printed line as its value, so the mapper reconstructs that exact text for every trailer-page line it can source:
    - From the Quote itself: `quote_number_line` (`"Quote #:{Quote Name}"`), `reseller_end_user_line` (`"Reseller/ End User: {Account Name}"`), `contact_person_line`/`tel_nr_line`/`email_line` (from the Quote's primary Contact — `SBQQ__PrimaryContact__r.Name`/`Phone`/`Email`), `address_block` (from the Quote's `SBQQ__Shipping*__c` fields), and `payment_terms_line` (from `SBQQ__PaymentTerms__c`, used as a fallback — see below).
    - From the related `Order` (best-effort lookup by the Quote's Opportunity, see `salesforce_client._get_order_data`): `reseller_po_number_line` (`End_User_PO__c`), `shipment_terms_line` (`Shipping_Method__c`), and `payment_terms_line` (`Payment_Terms__c`, preferred over the Quote's own value when an Order exists). An Order may not exist yet if the PO is being generated ahead of the deal closing — in that case these three fields are simply left unset (unchanged/manual) rather than erroring.
    - `address_block`'s `FieldBox` only has room for 2 printed lines before it collides with `email_line` below it, so the mapper joins all of the Quote's shipping-street lines into a single line and city/state/postal code/country into a second line — a street address with, e.g., a separate "Suite/Unit" line won't print on its own line, but will still appear, space-joined, in the first line.
  - Any other/unrecognized distributor falls back to the `arrow-ecs-sau` mapping (`quote_number`/`buyer`), which simply won't match that distributor's field keys and so populates nothing — everything stays manual entry.
- Line items are distributor-agnostic and populate the same way for every distributor whose table has these column keys: `part_number` (the Quote Line's `Printable_Product__c`, falling back to the Product's `ProductCode`, e.g. `RS-UR-FE-MS-PE-PA`, when it's blank), `description` (the Quote Line's own `SBQQ__Description__c`, not the Product's Name/Code, which is just the SKU), `qty`, `unit_cost`, `terms`.
- The distributor dropdown auto-selects based on the Quote's Opportunity `Distributor_Lookup__r.Name` matching a name in `config.DISTRIBUTORS`; if there's no match, pick a distributor and load its template manually, then click "Use this Quote" again to merge in the pulled data. If a distributor is already loaded when you pull a Quote, its slug is sent to the server and takes priority over auto-detection, so the fields returned always match what's on screen.
- Quote search matches only the Quote Name, not the Account or Opportunity name.

## Email addresses are forced to `sandbox.com`

Every email address in a field value has its domain replaced with `sandbox.com` (the part before the `@` is kept, so `rubriklog@computergross.it` becomes `rubriklog@sandbox.com`). This is applied in `main.py` through `sandbox_email.py` at the three points field values cross the API — the template load, the Salesforce quote pull, and the generate/preview request — so it covers every distributor and can't be bypassed by typing a real address into the form. Addresses embedded in longer text (e.g. a shipping reference line or an IOR contact line) are rewritten in place. The domain is set by `config.SANDBOX_EMAIL_DOMAIN`.

Limitations:
- Static letterhead text that isn't an editable field (e.g. NextGen's own `operations.au@nextgen.group` line at the top right, `info@adn.de` and `quotes.ecs.nl@arrow.com` in the footers) is part of the template and is not changed.
- The original address of a replaced field stays in the PDF's hidden text layer under the white cover box (it looks right on screen, but copy/paste or text search of the PDF can still find it).

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp env.example .env   # adjust PORT / SALESFORCE_ORG_ALIAS if needed
```

## Run

Standalone:

```bash
uvicorn main:app --reload --port 8010
```

Visit http://127.0.0.1:8010/

Embedded in the Order Validation App, `pages/PO_Processing_Engine.py` starts this same server itself (with `sys.executable -m uvicorn`) on port **8012** (`PO_ENGINE_PORT` overrides it) and shows it in an iframe; "Open in a new tab" goes to `http://127.0.0.1:8012/`. 8012 is deliberately not 8011, so a copy of the app from another checkout can't leave an engine on the port that this copy then reuses with different code.

## Structure

```
po-processing-engine/
  main.py              # FastAPI app: static mount, index route, /api/health, distributor + Salesforce + generate endpoints
  config.py            # BASE_DIR, PORT, SALESFORCE_ORGS, DISTRIBUTORS, SANDBOX_EMAIL_DOMAIN
  salesforce_client.py # Read-only Salesforce CLI (`sf`) query wrapper for the Quote pull feature
  sandbox_email.py     # Forces every email address in field values to sandbox.com
  requirements.txt
  env.example
  templates/index.html
  static/              # style.css, script.js
  pdf_engine/
    extractor.py       # Loads a template PDF into editable fields/line items (dispatches to a parser or layout)
    generator.py       # Coordinate-layout generator (used by distributors with a DistributorLayout)
    generator_<disti>.py   # Dedicated generator per distributor
    parsers/<disti>.py     # Dedicated template parser per distributor
    layouts/               # DistributorLayout definitions (arrow-ecs-sau, exclusive-networks-south-africa)
    paginate.py, models.py # Shared pagination / layout helpers
    sandbox_pdf.py     # Rewrites email addresses printed in the generated PDF
  data/
    uploads/           # future: ad-hoc uploaded source PDFs (not tied to a known distributor)
    templates/<slug>/  # the sample PO PDF for each distributor (Old/ holds retired samples)
    generated/<slug>/  # regenerated output PDFs (git-ignored)
```

## Distributors

`config.DISTRIBUTORS` maps a slug to a display name and drives `GET /api/distributors`. The slug is also the folder name under `data/templates/` and `data/generated/`, so the newer entries use the display name itself (spaces and punctuation included) as the slug. The first six entries in the config are legacy kebab-case slugs.

| Slug | Display name | Template | Parser | Generator | In dropdown |
|---|---|---|---|---|---|
| `ADN Distribution GmbH` | ADN Distribution GmbH | yes | yes | yes | yes |
| `Arrow (Netherlands)` | Arrow ECS BV (Netherlands) | yes | yes | yes | yes |
| `Computer Gross spa` | Computer Gross spa | yes | yes | yes | yes |
| `Exclusive Networks (Norway)` | Exclusive Networks (Norway) | yes | yes | yes | yes |
| `Ingram Micro Canada` | Ingram Micro Canada | yes | yes | yes | yes |
| `Innocom Ltd` | Innocom Ltd | yes | yes | yes | yes |
| `Networld Corporation` | Networld Corporation | yes | yes | yes | yes |
| `NextGen Distribution Pty Ltd` | NextGen Distribution Pty Ltd | yes | yes | yes | yes |
| `NOX Co.,LTD.` | NOX Co.,LTD. | yes | yes | yes | yes |
| `iValue InfoSolutions Limited` | iValue InfoSolutions Limited | yes | no | no | yes, but returns "not yet configured" |
| `HCL America, Inc.` | HCL America, Inc. | no | no | no | yes, but returns an error |
| `arrow-ecs-sau` | ARROW E.C.S., SAU | in `templates/Old/` | layout | layout | hidden |
| `exclusive-networks-south-africa` | Exclusive Networks (South Africa) | in `templates/Old/` | layout | layout | hidden |
| `pt-synnex-metrodata-indonesia`, `pt-ecs-indo-jaya`, `hcl`, `exclusive-networks-turkey` | legacy placeholders | no | no | no | hidden |

"Hidden" slugs are filtered out of the dropdown by `HIDDEN_DISTRIBUTOR_SLUGS` in `static/script.js` but are still returned by the API. The two layout-based distributors need their sample PDF moved back from `templates/Old/<slug>/` to `templates/<slug>/` before they will load.

The list lives in one place, `distributors.py` (`REGISTRY`). Each entry gives the slug, display name, whether it is hidden from the dropdown, and "module:function" references to its parser, generator, layout and Salesforce field mapper. `config.DISTRIBUTORS` is derived from it, and the app checks at startup that every reference resolves. To add a distributor, write its parser and generator modules, drop its sample PDF in `data/templates/<slug>/`, and add one `Distributor(...)` entry. The only other place that knows about distributors is `HIDDEN_DISTRIBUTOR_SLUGS` in `static/script.js`, which should be kept in step with the `hidden=True` entries.
