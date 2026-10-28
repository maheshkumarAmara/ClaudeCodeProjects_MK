#!/usr/bin/env node
/**
 * Regenerates scripts/soql-builder/schema.js from force-app/main/default/objects/**.
 *
 * Walks every object folder, pulls a handful of leaf tags out of each
 * *.object-meta.xml and fields/*.field-meta.xml file via regex (this repo has
 * no XML-parsing dependency and the tags we need are simple, non-nested leaf
 * elements), and emits a single JS data file the SOQL builder UI loads via
 * <script src="schema.js"> (works offline under file://, unlike fetch()'ing
 * a .json file, which most browsers block for local files).
 *
 * Usage: node scripts/soql-builder/build-schema.mjs
 */
import { readFileSync, readdirSync, existsSync, statSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HERE, "..", "..");
const OBJECTS_ROOT = join(REPO_ROOT, "force-app", "main", "default", "objects");
const OUT_FILE = join(HERE, "schema.js");

const XML_ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'" };
function decodeXmlEntities(text) {
  return text.replace(/&(amp|lt|gt|quot|apos);/g, (_, name) => XML_ENTITIES[name]);
}

/** Extract the text content of the first `<tag>...</tag>` in xml, or null. */
function extractTag(xml, tag) {
  const match = xml.match(new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`));
  return match ? decodeXmlEntities(match[1].trim()) : null;
}

/**
 * Extract the text content of every `<tag>...</tag>` in xml. Polymorphic
 * lookup fields (e.g. Task.WhoId/WhatId) repeat <referenceTo> once per
 * target object, which extractTag's single-match regex would silently
 * truncate to just the first one.
 */
function extractAllTags(xml, tag) {
  const matches = xml.matchAll(new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`, "g"));
  return [...matches].map((m) => decodeXmlEntities(m[1].trim()));
}

// Some standard-object lookup fields are retrieved as bare stubs (only
// <fullName>/<type>, no <referenceTo>/<relationshipName>) because the
// reference is implicit to the platform and Salesforce doesn't always echo
// it back in metadata retrieval — e.g. OrderItem/fields/OrderId.field-meta.xml
// is literally just `<fullName>OrderId</fullName><type>Lookup</type>`. These
// are fixed, documented standard-schema relationships (not guesses), so we
// fill them in only when the file itself is missing the data, keyed by
// "ChildObject.FieldName" -> { referenceTo, relationshipName }.
const STANDARD_FIELD_REFERENCES = {
  "OrderItem.OrderId": { referenceTo: "Order", relationshipName: "OrderItems" },
  "OrderItem.PricebookEntryId": { referenceTo: "PricebookEntry", relationshipName: "PricebookEntry" },
  "Order.AccountId": { referenceTo: "Account", relationshipName: "Orders" },
  "Order.ContractId": { referenceTo: "Contract", relationshipName: "Orders" },
  "Order.OpportunityId": { referenceTo: "Opportunity", relationshipName: "Orders" },
  "OpportunityLineItem.OpportunityId": { referenceTo: "Opportunity", relationshipName: "OpportunityLineItems" },
  "OpportunityLineItem.PricebookEntryId": { referenceTo: "PricebookEntry", relationshipName: "PricebookEntry" },
  "QuoteLineItem.QuoteId": { referenceTo: "Quote", relationshipName: "QuoteLineItems" },
  "ContractLineItem.ContractId": { referenceTo: "Contract", relationshipName: "ContractLineItems" },
  "Quote.OpportunityId": { referenceTo: "Opportunity", relationshipName: "Quotes" },
  "Contract.AccountId": { referenceTo: "Account", relationshipName: "Contracts" },
  "Case.AccountId": { referenceTo: "Account", relationshipName: "Cases" },
  "Contact.AccountId": { referenceTo: "Account", relationshipName: "Contacts" },
  "Opportunity.AccountId": { referenceTo: "Account", relationshipName: "Opportunities" },
  "Asset.AccountId": { referenceTo: "Account", relationshipName: "Assets" },
  "CaseComment.ParentId": { referenceTo: "Case", relationshipName: "CaseComments" },
  "CampaignMember.CampaignId": { referenceTo: "Campaign", relationshipName: "CampaignMembers" },
};

const warnings = [];
const objects = {};
const childRelationships = {};

const objectDirs = readdirSync(OBJECTS_ROOT, { withFileTypes: true })
  .filter((entry) => entry.isDirectory())
  .map((entry) => entry.name)
  .sort();

for (const apiName of objectDirs) {
  const objectDir = join(OBJECTS_ROOT, apiName);
  const objectMetaFile = join(objectDir, `${apiName}.object-meta.xml`);

  let label = apiName;
  if (existsSync(objectMetaFile)) {
    const xml = readFileSync(objectMetaFile, "utf8");
    label = extractTag(xml, "label") ?? apiName;
  }

  const fields = [];
  const fieldsDir = join(objectDir, "fields");
  if (existsSync(fieldsDir) && statSync(fieldsDir).isDirectory()) {
    const fieldFiles = readdirSync(fieldsDir).filter((f) => f.endsWith(".field-meta.xml"));
    for (const fieldFile of fieldFiles) {
      const xml = readFileSync(join(fieldsDir, fieldFile), "utf8");
      const fullName = extractTag(xml, "fullName");
      if (!fullName) {
        warnings.push(`${apiName}/fields/${fieldFile}: no <fullName>, skipped`);
        continue;
      }

      const type = extractTag(xml, "type") ?? "Unknown";
      const fieldLabel = extractTag(xml, "label") ?? fullName;
      let referenceTo = extractTag(xml, "referenceTo");
      let relationshipName = extractTag(xml, "relationshipName");
      let relationshipFromStandardFallback = false;

      if (!referenceTo && !relationshipName) {
        const fallback = STANDARD_FIELD_REFERENCES[`${apiName}.${fullName}`];
        if (fallback) {
          referenceTo = fallback.referenceTo;
          relationshipName = fallback.relationshipName;
          relationshipFromStandardFallback = true;
        }
      }

      // <relationshipName> in field-meta.xml stores the bare metadata name
      // (e.g. "CPQ_Quote_Rate_Card_Lines"), but Salesforce requires a
      // "__r" suffix on custom relationships when used as a child subquery
      // in SOQL ("... FROM CPQ_Quote_Rate_Card_Lines__r"). The hardcoded
      // standard-field fallbacks above are already valid SOQL relationship
      // names (e.g. "OrderItems") and must not get a suffix appended.
      if (relationshipName && !relationshipFromStandardFallback && fullName.endsWith("__c")) {
        relationshipName = `${relationshipName}__r`;
      }

      const field = { name: fullName, label: fieldLabel, type };
      if (referenceTo) field.referenceTo = referenceTo;
      if (relationshipName) field.relationshipName = relationshipName;

      // Additive only: keep the existing single-string `referenceTo` (every
      // consumer treats it as one object) and separately expose the full
      // list of polymorphic targets for anything that wants to use it, e.g.
      // Task.WhoId -> Contact/Lead, Task.WhatId -> many objects.
      if (!relationshipFromStandardFallback) {
        const allReferenceTo = extractAllTags(xml, "referenceTo");
        if (allReferenceTo.length > 1) field.referenceToAll = allReferenceTo;
      }
      fields.push(field);

      if (referenceTo && relationshipName) {
        (childRelationships[referenceTo] ??= []).push({
          relationshipName,
          childObject: apiName,
          field: fullName,
        });
      }
    }
    fields.sort((a, b) => a.name.localeCompare(b.name));
  }

  objects[apiName] = { label, fields };
}

const schema = {
  objects,
  childRelationships,
  generatedAt: new Date().toISOString(),
};

const contents =
  `// Generated by scripts/soql-builder/build-schema.mjs — do not hand-edit.\n` +
  `// Regenerate with: npm run build:soql-schema\n` +
  `const SCHEMA = ${JSON.stringify(schema)};\n` +
  `if (typeof module !== "undefined") { module.exports = SCHEMA; }\n`;

writeFileSync(OUT_FILE, contents);

const totalFields = Object.values(objects).reduce((sum, o) => sum + o.fields.length, 0);
console.log(`Wrote ${OUT_FILE}`);
console.log(`  objects: ${Object.keys(objects).length}`);
console.log(`  fields:  ${totalFields}`);
console.log(`  child relationships: ${Object.keys(childRelationships).length} parent objects`);
if (warnings.length) {
  console.log(`  warnings: ${warnings.length}`);
  for (const w of warnings.slice(0, 20)) console.log(`    - ${w}`);
  if (warnings.length > 20) console.log(`    ...and ${warnings.length - 20} more`);
}
