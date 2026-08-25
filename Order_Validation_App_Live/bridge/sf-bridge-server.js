/**
 * sf-bridge-server.js
 * Local bridge: Salesforce CLI → EDI Order Management Tool (Distributors module)
 *
 * HOW TO START:
 *   cd <folder containing this file>
 *   node sf-bridge-server.js
 *
 * Keep this terminal window open while using the HTML tool.
 */

const http = require('http');
const fs = require('fs');
const path = require('path');
const { execFileSync, execSync } = require('child_process');
const os = require('os');

const SFTP_FOLDER = process.env.SFTP_UPLOAD_FOLDER || path.join(__dirname, '..', 'SFTP_Upload');

const PORT = 3001;

/* Auto-detect the Salesforce CLI path so the server works on any machine. */
function detectSfCli() {
    const cmd = os.platform() === 'win32' ? 'where sf' : 'which sf';
    try {
        return execSync(cmd, { encoding: 'utf8' }).trim().split('\n')[0].trim();
    } catch (_) {}
    /* Common fallback locations */
    const candidates = [
        '/usr/local/bin/sf',
        `${os.homedir()}/.local/bin/sf`,
        `${os.homedir()}/node_modules/.bin/sf`,
        '/opt/homebrew/bin/sf',
    ];
    for (const p of candidates) {
        try { execFileSync(p, ['--version'], { stdio: 'ignore' }); return p; } catch (_) {}
    }
    return null;
}

const SF_CLI = detectSfCli();
if (!SF_CLI) {
    console.error('ERROR: Salesforce CLI (sf) not found. Install it from https://developer.salesforce.com/tools/salesforcecli and re-run this server.');
    process.exit(1);
}
console.log(`Using Salesforce CLI: ${SF_CLI}`);

/* ── SOQL builder for EDI Vendors (mirrors the "Copy SOQL" logic in ediGenerator) ── */
const buildVendorSOQL = (orderNum, vendor, type) => {
    const o = orderNum.replace(/'/g, "\\'");
    const isSmci = ['smci_dropship', 'smci_inventory', 'smci_stocking'].includes(vendor);
    const needsCC =
        (['flash_partorder', 'flash_returnrepair'].includes(vendor) && ['855', '944', '997'].includes(type)) ||
        (vendor === 'flash_replenishment' && ['855', '997'].includes(type)) ||
        (vendor === 'tsp_techorder'       && type === '997');
    const isTsp855865 = (vendor === 'tsp_techorder' && ['855', '865'].includes(type));

    if (isSmci) {
        return `SELECT Order.SBQQ__Quote__r.Name, Order.OrderNumber, Product2.Name, Quantity, UnitPrice FROM OrderItem WHERE Order.OrderNumber='${o}'`;
    }
    if (isTsp855865) {
        return `SELECT id, Product_Name__c, Quantity, Failed_Serial_Number__c, Order.Cancel_RMA__c, order.ShippingCountryCode, order.Linked_RMA_Part_order__c FROM OrderItem WHERE Order.OrderNumber IN ('${o}')`;
    }
    if (needsCC) {
        return `SELECT id, Product_Name__c, Quantity, Failed_Serial_Number__c, Order.Cancel_RMA__c, order.ShippingCountryCode FROM OrderItem WHERE Order.OrderNumber IN ('${o}')`;
    }
    return `SELECT id, Product_Name__c, Quantity, Failed_Serial_Number__c, Order.Cancel_RMA__c FROM OrderItem WHERE Order.OrderNumber IN ('${o}')`;
};

/* ── SOQL builders for Lead Time, Shipment ASPEN, POC Dates, Stage PO ── */
const buildLeadTimeSOQL = (orderNum) => {
    const o = orderNum.replace(/'/g, "\\'");
    return `SELECT order.OrderNumber,order.customer_required_ship_date__c,order.Order_Accepted_Timestamp__c,order.Est_Ship_Date__c,order.Deliver_By__c,Product2.Shipping_Lead_Time__c FROM Orderitem WHERE order.OrderNumber='${o}'`;
};

const buildShipmentAspenSOQL = (quoteNum) => {
    const q = quoteNum.replace(/'/g, "\\'");
    return `SELECT SBQQ__Quote__r.id, SBQQ__Product__r.Name, SBQQ__Quantity__c, SBQQ__Quote__r.Name, SBQQ__Quote__r.SBQQ__Opportunity2__r.ContractManufacturer__c FROM SBQQ__QuoteLine__c WHERE SBQQ__Quote__r.Name = '${q}' AND SBQQ__Product__r.Product_Type__c IN ('Hardware','Accessories','Spares') AND Disposition_Reason__c NOT IN ('Renew Later','Renewing','Refreshed')`;
};

const buildPocSOQL = (orderNum, stage) => {
    const n = orderNum.replace(/'/g, "\\'");
    if (stage === 'POC Entitlement Created') {
        return `select Order_Service_Item__r.Order.Order_Number__c, Order_Service_Item__r.Product2.Name, Order_Service_Item__r.Order.SC_or_Entitlement_Stage__c, Order_Service_Item__r.Order.Actual_Order_Ship_Date__c, Order_Service_Item__r.Order.POC_Request__r.Most_Recent_End_Date__c, Order_Service_Item__r.Order.POC_Request__r.Approval_Status__c,StartDate,EndDate,Order_Service_Item__r.Support_Start_Date__c,Order_Service_Item__r.Support_End_Date__c from Entitlement where Order_Service_Item__r.order.Order_Number__c ='${n}'`;
    }
    return `SELECT Order.OrderNumber, order.SC_or_Entitlement_Stage__c, Order.Actual_Order_Ship_Date__c, order.POC_Request__r.Most_Recent_End_Date__c, order.POC_Request__r.Approval_Status__c, Product2.Name, Support_Start_Date__c, Support_End_Date__c , SBQQ__SubscriptionTerm__c FROM OrderItem WHERE Order.OrderNumber IN ('${n}')`;
};

const buildStagePoSOQL = (quoteNum) => {
    const q = quoteNum.replace(/'/g, "\\'");
    const inC = `IN ('${q}')`;
    return `select id,SBQQ__NetPrice__c,SBQQ__SubscriptionTerm__c,Printable_Product__c,SBQQ__Quantity__c,SBQQ__Quote__r.Name,SBQQ__Quote__r.SBQQ__NetAmount__c,SBQQ__Quote__r.SBQQ__Account__r.Name,SBQQ__Quote__r.SBQQ__Opportunity2__r.Distributor_Lookup__c,SBQQ__Quote__r.SBQQ__Opportunity2__r.Distributor_Lookup__r.Name,SBQQ__Quote__r.SBQQ__Opportunity2__r.ContractManufacturer__c,SBQQ__Quote__r.SBQQ__PaymentTerms__c from SBQQ__QuoteLine__c where SBQQ__Quote__r.Name ${inC} and SBQQ__Renewal__c!=true and (NOT (SBQQ__Product__r.Name Like 'RBK%')) and (NOT (SBQQ__Product__r.Name Like 'RHA%' or SBQQ__Product__r.Name Like 'RCA%')) and SBQQ__Optional__c=false`;
};

/* ── SOQL builder for MSP Pay Go Fulfillment ── */
const buildMspPayGoSOQL = (orderNum) => {
    const o = orderNum.replace(/'/g, "\\'");
    return `select order.OrderNumber, order.Order_Sub_Type__c, Printable_Product__c, order.Opportunity.FSI_Special_Program__c, order.Actual_Order_Ship_Date__c, Support_Start_Date__c, Support_End_Date__c, SBQQ__SubscriptionTerm__c, Support_Term__c from OrderItem where order.OrderNumber ='${o}'`;
};

/* ── SOQL builder for EntitlementLinks SR (mirrors copySoqlQuery in elsr module) ── */
const buildEntitlementSOQL = (original, replacement) => {
    const nums = [original, replacement]
        .filter(Boolean)
        .join(',')
        .split(',')
        .map(o => o.trim())
        .filter(o => o)
        .map(o => `'${o.replace(/'/g, "\\'")}'`)
        .join(',');
    return `select SBQQSC__OrderProduct__r.Order.OrderNumber, id, SBQQSC__Product__r.Name from ContractLineItem where SBQQSC__OrderProduct__r.Order.OrderNumber in (${nums}) and Product2.Replacement_Category__c != 'Not Replaceable' order by SBQQSC__OrderProduct__r.Order.OrderNumber desc`;
};

/* ── SOQL builder for Entitlement_Links__c (mirrors copyShipmentSoqlQuery in elsr module) ── */
const buildEntitlementLinksSOQL = (ids) => {
    const inClause = ids.map(id => `'${id.replace(/'/g, "\\'")}'`).join(',');
    return `select id,Name,Renewed_Entitlement__r.Name,Renewed_Entitlement__r.id,Previous_Entitlement__r.id,Renewed_Entitlement__r.Order_Service_Item__r.OrderId,Previous_Entitlement__r.Order_Service_Item__r.OrderId,Renewed_Entitlement__r.Order_Number__c,Previous_Entitlement__r.Order_Number__c,Previous_Entitlement__r.Name,Type__c,Renewed_Entitlement__r.Quantity__c,Previous_Entitlement__r.Quantity__c,Renewed_Entitlement__r.Renewal_Category__c,Previous_Entitlement__r.Renewal_Category__c,Renewed_Entitlement__r.Terminated_Date__c,Previous_Entitlement__r.Terminated_Date__c,Renewed_Entitlement__r.Source_StartDate__c,Previous_Entitlement__r.Source_StartDate__c,Previous_Entitlement__r.StartDate,Renewed_Entitlement__r.StartDate,Previous_Entitlement__r.EndDate,Renewed_Entitlement__r.EndDate,Renewed_Entitlement__r.Status,Previous_Entitlement__r.Status,Renewed_Entitlement__r.Entitlement_Status__c,Previous_Entitlement__r.Entitlement_Status__c,Renewed_Entitlement__r.Transaction_Type__c,Previous_Entitlement__r.Transaction_Type__c,Previous_Entitlement__r.Phantom_OrderItemID__r.Order.Order_Number__c,Renewed_Entitlement__r.Phantom_OrderItemID__r.Order.Order_Number__c from Entitlement_Links__c where Renewed_Entitlement__r.ContractLineItemId IN (${inClause}) or Previous_Entitlement__r.ContractLineItemId IN (${inClause}) order by Name`;
};

/* ── SOQL template (mirrors the existing "Copy SOQL" query in the HTML) ── */
const buildSOQL = (quoteNumbers) => {
    const inClause = quoteNumbers.map(q => `'${q.replace(/'/g, "\\'")}'`).join(',');
    return (
        'SELECT ' +
        'Printable_Product__c, ' +
        'SBQQ__Description__c, ' +
        'SBQQ__Quantity__c, ' +
        'SBQQ__SubscriptionTerm__c, ' +
        'SBQQ__NetPrice__c, ' +
        'SBQQ__Quote__r.SBQQ__Account__r.Name, ' +
        'SBQQ__Quote__r.Payment_year_1__c, ' +
        'SBQQ__Quote__r.Payment_year_2__c, ' +
        'SBQQ__Quote__r.Payment_year_3__c, ' +
        'SBQQ__Quote__r.SBQQ__Opportunity2__r.ContractManufacturer__c, ' +
        'SBQQ__Quote__r.SBQQ__PaymentTerms__c, ' +
        'SBQQ__Quote__r.SBQQ__Opportunity2__r.Distributor_Lookup__r.Name ' +
        'FROM SBQQ__QuoteLine__c ' +
        'WHERE SBQQ__Renewal__c != true ' +
        "AND (NOT (SBQQ__Product__r.Name LIKE 'RHA%' OR SBQQ__Product__r.Name LIKE 'RCA%')) " +
        'AND SBQQ__Optional__c = false ' +
        `AND SBQQ__Quote__r.Name IN (${inClause})`
    );
};

/* ── Helpers ── */
const jsonRes = (res, status, payload) => {
    const body = JSON.stringify(payload);
    res.writeHead(status, {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body),
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
    });
    res.end(body);
};

const readBody = (req) => new Promise((resolve, reject) => {
    let raw = '';
    req.on('data', chunk => { raw += chunk; });
    req.on('end', () => { try { resolve(JSON.parse(raw)); } catch (e) { reject(e); } });
    req.on('error', reject);
});

const runSF = (args) => {
    const raw = execFileSync(SF_CLI, args, {
        timeout: 60000,
        encoding: 'utf8',
        maxBuffer: 20 * 1024 * 1024,
    });
    return JSON.parse(raw);
};

/* ── Request handler ── */
const server = http.createServer(async (req, res) => {
    /* CORS preflight */
    if (req.method === 'OPTIONS') {
        res.writeHead(204, {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
        });
        return res.end();
    }

    const { pathname, searchParams } = new URL(req.url, `http://localhost:${PORT}`);

    /* ── GET /api/status — list authenticated SF orgs ── */
    if (pathname === '/api/status') {
        try {
            const data = runSF(['org', 'list', '--json']);
            const raw = [
                ...(data.result?.nonScratchOrgs || []),
                ...(data.result?.sandboxes || []),
            ];
            const seen = new Set();
            const orgs = raw
                .filter(o => {
                    if (seen.has(o.username)) return false;
                    seen.add(o.username);
                    return true;
                })
                .map(o => ({
                    alias: o.alias || '',
                    username: o.username || '',
                    isDefault: !!(o.isDefault || o.isDefaultUsername),
                }));
            return jsonRes(res, 200, { connected: true, orgs });
        } catch (err) {
            let msg = err.message;
            if (err.stdout) { try { msg = JSON.parse(err.stdout).message || msg; } catch {} }
            const needsReauth = /expired|refresh token/i.test(msg);
            return jsonRes(res, 200, { connected: false, error: msg, needsReauth });
        }
    }

    /* ── GET /api/soql?quote=Q-123&org=rbkqa — run SOQL via SF CLI ── */
    if (pathname === '/api/soql') {
        const quoteParam = searchParams.get('quote');
        const org = searchParams.get('org') || '';

        if (!quoteParam) {
            return jsonRes(res, 400, { error: 'quote parameter is required' });
        }

        const quoteNumbers = quoteParam.split(',').map(q => q.trim()).filter(Boolean);
        if (!quoteNumbers.length) {
            return jsonRes(res, 400, { error: 'No valid quote numbers supplied' });
        }

        const soql = buildSOQL(quoteNumbers);
        const args = ['data', 'query', '--query', soql, '--json'];
        if (org) args.push('--target-org', org);

        try {
            const data = runSF(args);
            const records = data.result?.records || [];
            return jsonRes(res, 200, { success: true, records });
        } catch (err) {
            let msg = err.message;
            if (err.stdout) {
                try { msg = JSON.parse(err.stdout).message || msg; } catch {}
            }
            console.error('[SF CLI error]', msg);
            return jsonRes(res, 500, { error: msg });
        }
    }

    /* ── GET /api/vendor-soql?order=ORDER_NUM&vendor=flash_partorder&type=855&org=rbkqa ── */
    if (pathname === '/api/vendor-soql') {
        const orderParam = searchParams.get('order');
        const vendor     = searchParams.get('vendor') || '';
        const type       = searchParams.get('type')   || '';
        const org        = searchParams.get('org')    || '';

        if (!orderParam) {
            return jsonRes(res, 400, { error: 'order parameter is required' });
        }

        const soql = buildVendorSOQL(orderParam.trim(), vendor, type);
        const args = ['data', 'query', '--query', soql, '--json'];
        if (org) args.push('--target-org', org);

        try {
            const data    = runSF(args);
            const records = data.result?.records || [];
            return jsonRes(res, 200, { success: true, records, vendor, type });
        } catch (err) {
            let msg = err.message;
            if (err.stdout) { try { msg = JSON.parse(err.stdout).message || msg; } catch {} }
            console.error('[SF CLI vendor error]', msg);
            return jsonRes(res, 500, { error: msg });
        }
    }

    /* ── GET /api/lead-time-soql?order=ORDER_NUM&org=rbkqa ── */
    if (pathname === '/api/lead-time-soql') {
        const orderParam = searchParams.get('order') || '';
        const org        = searchParams.get('org')   || '';
        if (!orderParam) return jsonRes(res, 400, { error: 'order parameter is required' });
        const soql = buildLeadTimeSOQL(orderParam.trim());
        const args = ['data', 'query', '--query', soql, '--json'];
        if (org) args.push('--target-org', org);
        try {
            const data = runSF(args);
            return jsonRes(res, 200, { success: true, records: data.result?.records || [] });
        } catch (err) {
            let msg = err.message;
            if (err.stdout) { try { msg = JSON.parse(err.stdout).message || msg; } catch {} }
            console.error('[SF CLI lead-time error]', msg);
            return jsonRes(res, 500, { error: msg });
        }
    }

    /* ── GET /api/shipment-aspen-soql?quote=QUOTE_NUM&org=rbkqa ── */
    if (pathname === '/api/shipment-aspen-soql') {
        const quoteParam = searchParams.get('quote') || '';
        const org        = searchParams.get('org')   || '';
        if (!quoteParam) return jsonRes(res, 400, { error: 'quote parameter is required' });
        const soql = buildShipmentAspenSOQL(quoteParam.trim());
        const args = ['data', 'query', '--query', soql, '--json'];
        if (org) args.push('--target-org', org);
        try {
            const data = runSF(args);
            return jsonRes(res, 200, { success: true, records: data.result?.records || [] });
        } catch (err) {
            let msg = err.message;
            if (err.stdout) { try { msg = JSON.parse(err.stdout).message || msg; } catch {} }
            console.error('[SF CLI shipment-aspen error]', msg);
            return jsonRes(res, 500, { error: msg });
        }
    }

    /* ── GET /api/poc-soql?order=ORDER_NUM&stage=Create+POC+Entitlement&org=rbkqa ── */
    if (pathname === '/api/poc-soql') {
        const orderParam = searchParams.get('order') || '';
        const stage      = searchParams.get('stage') || '';
        const org        = searchParams.get('org')   || '';
        if (!orderParam) return jsonRes(res, 400, { error: 'order parameter is required' });
        if (!stage) return jsonRes(res, 400, { error: 'stage parameter is required' });
        const soql = buildPocSOQL(orderParam.trim(), stage);
        const args = ['data', 'query', '--query', soql, '--json'];
        if (org) args.push('--target-org', org);
        try {
            const data = runSF(args);
            return jsonRes(res, 200, { success: true, records: data.result?.records || [], stage });
        } catch (err) {
            let msg = err.message;
            if (err.stdout) { try { msg = JSON.parse(err.stdout).message || msg; } catch {} }
            console.error('[SF CLI poc error]', msg);
            return jsonRes(res, 500, { error: msg });
        }
    }

    /* ── GET /api/stage-po-soql?quote=QUOTE_NUM&org=rbkqa ── */
    if (pathname === '/api/stage-po-soql') {
        const quoteParam = searchParams.get('quote') || '';
        const org        = searchParams.get('org')   || '';
        if (!quoteParam) return jsonRes(res, 400, { error: 'quote parameter is required' });
        const soql = buildStagePoSOQL(quoteParam.trim());
        const args = ['data', 'query', '--query', soql, '--json'];
        if (org) args.push('--target-org', org);
        try {
            const data = runSF(args);
            return jsonRes(res, 200, { success: true, records: data.result?.records || [] });
        } catch (err) {
            let msg = err.message;
            if (err.stdout) { try { msg = JSON.parse(err.stdout).message || msg; } catch {} }
            console.error('[SF CLI stage-po error]', msg);
            return jsonRes(res, 500, { error: msg });
        }
    }

    /* ── GET /api/msp-paygo-soql?order=ORDER_NUM&org=rbkqa ── */
    if (pathname === '/api/msp-paygo-soql') {
        const orderParam = searchParams.get('order') || '';
        const org        = searchParams.get('org')   || '';
        if (!orderParam) return jsonRes(res, 400, { error: 'order parameter is required' });
        const soql = buildMspPayGoSOQL(orderParam.trim());
        const args = ['data', 'query', '--query', soql, '--json'];
        if (org) args.push('--target-org', org);
        try {
            const data = runSF(args);
            return jsonRes(res, 200, { success: true, records: data.result?.records || [] });
        } catch (err) {
            let msg = err.message;
            if (err.stdout) { try { msg = JSON.parse(err.stdout).message || msg; } catch {} }
            console.error('[SF CLI msp-paygo error]', msg);
            return jsonRes(res, 500, { error: msg });
        }
    }

    /* ── GET /api/entitlement-soql?original=84673&replacement=90391&org=rbkqa ── */
    if (pathname === '/api/entitlement-soql') {
        const original    = searchParams.get('original')    || '';
        const replacement = searchParams.get('replacement') || '';
        const org         = searchParams.get('org')         || '';

        if (!original && !replacement) {
            return jsonRes(res, 400, { error: 'original or replacement parameter is required' });
        }

        const soql = buildEntitlementSOQL(original, replacement);
        const args = ['data', 'query', '--query', soql, '--json'];
        if (org) args.push('--target-org', org);

        try {
            const data    = runSF(args);
            const records = data.result?.records || [];
            return jsonRes(res, 200, { success: true, records });
        } catch (err) {
            let msg = err.message;
            if (err.stdout) { try { msg = JSON.parse(err.stdout).message || msg; } catch {} }
            console.error('[SF CLI entitlement error]', msg);
            return jsonRes(res, 500, { error: msg });
        }
    }

    /* ── GET /api/quote-order-numbers?quote=Q-846992&org=rbkqa ── */
    if (pathname === '/api/quote-order-numbers') {
        const quote = searchParams.get('quote') || '';
        const org   = searchParams.get('org')   || '';
        if (!quote) return jsonRes(res, 400, { error: 'quote parameter is required' });
        const q = quote.replace(/'/g, "\\'");
        const soql = `select SBQQ__QuoteLine__r.SBQQ__Quote__r.Name,order.OrderNumber from OrderItem where SBQQ__QuoteLine__r.SBQQ__Quote__r.Name='${q}'`;
        const args = ['data', 'query', '--query', soql, '--json'];
        if (org) args.push('--target-org', org);
        try {
            const data = runSF(args);
            const records = data.result?.records || [];
            const orderNumbers = [...new Set(records.map(r => r.Order?.OrderNumber).filter(Boolean))];
            return jsonRes(res, 200, { success: true, orderNumbers });
        } catch (err) {
            let msg = err.message;
            if (err.stdout) { try { msg = JSON.parse(err.stdout).message || msg; } catch {} }
            console.error('[SF CLI quote-order-numbers error]', msg);
            return jsonRes(res, 500, { error: msg });
        }
    }

    /* ── GET /api/previous-transaction-ref?orderNumbers=107647,108000&org=rbkqa ── */
    if (pathname === '/api/previous-transaction-ref') {
        const orderNumbersParam = searchParams.get('orderNumbers') || '';
        const org               = searchParams.get('org')          || '';
        if (!orderNumbersParam) return jsonRes(res, 400, { error: 'orderNumbers parameter is required' });
        const orderNumbers = orderNumbersParam.split(',').map(n => n.trim()).filter(Boolean);
        if (!orderNumbers.length) return jsonRes(res, 400, { error: 'No valid order numbers supplied' });
        const inClause = orderNumbers.map(n => `'${n.replace(/'/g, "\\'")}'`).join(',');
        const soql = `select id,Previous_Transaction_Reference__c from orderitem where order.OrderNumber in (${inClause})`;
        const args = ['data', 'query', '--query', soql, '--json'];
        if (org) args.push('--target-org', org);
        try {
            const data = runSF(args);
            return jsonRes(res, 200, { success: true, records: data.result?.records || [] });
        } catch (err) {
            let msg = err.message;
            if (err.stdout) { try { msg = JSON.parse(err.stdout).message || msg; } catch {} }
            console.error('[SF CLI previous-transaction-ref error]', msg);
            return jsonRes(res, 500, { error: msg });
        }
    }

    /* ── GET /api/entitlement-links-soql?soql=<fullSOQL>&org=rbkqa ── */
    if (pathname === '/api/entitlement-links-soql') {
        const soqlParam = searchParams.get('soql') || '';
        const idsParam  = searchParams.get('ids')  || '';
        const org       = searchParams.get('org')  || '';
        let soql;
        if (soqlParam) {
            soql = soqlParam;
        } else {
            if (!idsParam) return jsonRes(res, 400, { error: 'soql or ids parameter is required' });
            const ids = idsParam.split(',').map(id => id.trim()).filter(Boolean);
            if (!ids.length) return jsonRes(res, 400, { error: 'No valid IDs supplied' });
            soql = buildEntitlementLinksSOQL(ids);
        }
        console.log('[entitlement-links] running SOQL:', soql.slice(0, 120) + '...');
        const args = ['data', 'query', '--query', soql, '--json'];
        if (org) args.push('--target-org', org);
        try {
            const data = runSF(args);
            return jsonRes(res, 200, { success: true, records: data.result?.records || [] });
        } catch (err) {
            let msg = err.message;
            if (err.stdout) { try { msg = JSON.parse(err.stdout).message || msg; } catch {} }
            console.error('[SF CLI entitlement-links error]', msg);
            return jsonRes(res, 500, { error: msg });
        }
    }

    /* ── POST /api/save-to-sftp-folder — write EDI file to local SFTP hot folder ── */
    if (req.method === 'POST' && pathname === '/api/save-to-sftp-folder') {
        try {
            const { filename, content } = await readBody(req);
            if (!filename || content === undefined) {
                return jsonRes(res, 400, { error: 'filename and content are required' });
            }
            if (!fs.existsSync(SFTP_FOLDER)) fs.mkdirSync(SFTP_FOLDER, { recursive: true });
            const filePath = path.join(SFTP_FOLDER, filename);
            fs.writeFileSync(filePath, content.replace(/\n/g, '\r\n'), 'utf8');
            console.log(`[SFTP folder] Saved: ${filePath}`);
            return jsonRes(res, 200, { success: true, path: filePath });
        } catch (err) {
            console.error('[SFTP folder error]', err.message);
            return jsonRes(res, 500, { error: err.message });
        }
    }

    jsonRes(res, 404, { error: 'Not found' });
});

server.listen(PORT, '127.0.0.1', () => {
    console.log('');
    console.log('  Salesforce CLI Bridge Server');
    console.log(`  Listening on http://localhost:${PORT}`);
    console.log('');
    console.log('  Endpoints:');
    console.log(`    GET /api/status           — list authenticated SF orgs`);
    console.log(`    GET /api/soql?quote=Q-xxx — fetch QuoteLine data`);
    console.log('');
    console.log('  Keep this window open while using the EDI tool.');
    console.log('  Press Ctrl+C to stop.');
    console.log('');
});
