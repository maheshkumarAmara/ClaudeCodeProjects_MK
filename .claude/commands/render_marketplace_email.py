#!/usr/bin/env python3
"""Marketplace email renderer - outputs JSON {subject, html} to stdout."""

import sys, json, base64, argparse

def decode_data(b64):
    return json.loads(base64.b64decode(b64).decode('utf-8'))

def render_aws(q, d):
    subject = f"AWS Marketplace Offer Accepted - Agreement Created for {q}"
    html = f"""<p>Greetings from AWS Marketplace,</p>
<p>An AWS Marketplace offer has been accepted by AWS account: {d['accountId']} on {d['startDate']}, and an agreement was created.</p>
<p>Review the following details:</p>
<p><u>Customer details</u><br>
<b>Company name</b>: {d['companyName']}<br>
<b>Customer AWS account ID</b>: {d['accountId']}</p>
<p><u>Product details</u><br>
<b>Product name</b>: {d['productName']}<br>
<b>Product ID</b>: {d['productId']}</p>
<p><u>Offer details</u><br>
<b>Offer name</b>: {d['offerName']}<br>
<b>Offer ID</b>: {d['offerId']}</p>
<p><u>Agreement details</u><br>
<b>Agreement ID</b>: {d['agreementId']}<br>
<b>Agreement start date</b>: {d['startDate']}<br>
<b>Agreement end date</b>: {d['endDate']}<br>
<b>Purchase amount</b>: {d['amount']} (USD)</p>
<p>The customer will receive entitlements to the product on {d['startDate']}. If there are processing issues, you will be notified in a separate email.</p>
<p>Visit the <a href="https://aws.amazon.com/marketplace/management">AWS Marketplace Management Portal (AMMP)</a> to find additional details. For data products, please go to the <a href="https://console.aws.amazon.com/dataexchange">AWS Data Exchange console</a>.</p>
<p>Regards,<br>The AWS Marketplace Team</p>"""
    return subject, html

def render_aws_partner(q, d):
    subject = f"AWS Marketplace Offer Accepted - Agreement Created for {q}"
    html = f"""<p>Greetings from AWS Marketplace,</p>
<p>An AWS Marketplace offer has been accepted by AWS account: {d['accountId']} on {d['startDate']}, and an agreement was created.</p>
<p>Review the following details:</p>
<p><u>Customer details</u><br>
<b>Company name</b>: {d['companyName']}<br>
<b>Customer AWS account ID</b>: {d['accountId']}</p>
<p><u>Channel partner details</u><br>
<b>Channel partner</b>: {d.get('channelPartner','')}<br>
<b>Channel partner AWS account ID</b>: {d.get('channelPartnerId','')}</p>
<p><u>Product details</u><br>
<b>Product name</b>: {d['productName']}<br>
<b>Product ID</b>: {d['productId']}</p>
<p><u>Offer details</u><br>
<b>Offer name</b>: {d['offerName']}<br>
<b>Offer ID</b>: {d['offerId']}</p>
<p><u>Agreement details</u><br>
<b>Agreement ID</b>: {d['agreementId']}<br>
<b>Agreement start date</b>: {d['startDate']}<br>
<b>Agreement end date</b>: {d['endDate']}<br>
<b>Wholesale price</b>: {d['amount']} (USD)</p>
<p>The customer will receive entitlements to the product on {d['startDate']}. If there are processing issues, you will be notified in a separate email.</p>
<p>Visit the <a href="https://aws.amazon.com/marketplace/management/agreements">AWS Marketplace Management Portal (AMMP)</a> to find additional details. For data products, please go to the <a href="https://console.aws.amazon.com/dataexchange">AWS Data Exchange console</a>.</p>
<p>Regards,<br>The AWS Marketplace Team</p>"""
    return subject, html

def _p(style, content):
    return f'<p style="font-family:Helvetica,Arial,sans-serif;margin-top:0px;margin-bottom:0px;font-size:14px;line-height:22px;color:#505f79;word-break:break-all;">{content}</p>'

def render_gcp_direct(d):
    co = d['companyName']; acc = d['accountId']; prod = d['productName']
    pid = d['productId']; oid = d['offerId']; eid = d['agreementId']
    st = d['startDate']; en = d['endDate']; sku = d['offerName']
    fn = d.get('gcpFullName',''); em = d.get('gcpEmail','')
    ph = d.get('gcpPhone',''); web = d.get('gcpWebsite',''); bill = d.get('gcpBilling','')
    subject = f"[Cloud Marketplace] New GCP Order of {prod} from {co}"
    html = f"""<div style="background-color:#dfe1e6;font-family:Helvetica,Arial,sans-serif;padding:0;font-size:0;line-height:0;">
  <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation"><tbody><tr>
    <td align="center" style="background-color:#dfe1e6;padding-left:8px;padding-right:8px;padding-top:32px;">
      <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody><tr>
        <td align="center" style="font-size:0;vertical-align:top;background-color:#253858;border-radius:12px 12px 0px 0px;padding-left:16px;padding-right:16px;padding-bottom:24px;">
          <div style="display:inline-block;vertical-align:top;width:100%;max-width:200px;">
            <div style="font-size:24px;line-height:24px;height:24px;">&nbsp;</div>
            <div style="font-family:Helvetica,Arial,sans-serif;font-size:16px;line-height:24px;text-align:center;padding-left:8px;padding-right:8px;">
              <p style="margin-top:0px;margin-bottom:0px;"><a href="https://tackle.io/" style="text-decoration:none;outline:none;color:#FFFFFF;"><img src="https://s3.amazonaws.com/tackle.io-misc/tackle-logo-light.png" width="80" height="24" alt="Tackle.io" style="max-width:80px;vertical-align:middle;border:0;"></a></p>
            </div>
          </div>
        </td>
      </tr></tbody></table>
    </td>
  </tr></tbody></table>
  <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation"><tbody><tr>
    <td align="center" style="background-color:#dfe1e6;padding-left:8px;padding-right:8px;">
      <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody><tr>
        <td align="center" style="font-family:Helvetica,Arial,sans-serif;font-size:19px;line-height:28px;background-color:#0052cc;color:#ffffff;padding-left:24px;padding-right:24px;padding-top:50px;padding-bottom:60px;">
          <table role="presentation" cellspacing="0" cellpadding="0" border="0"><tbody>
            <tr><td height="28" width="30" style="border-bottom:2px solid #ffffff;">&nbsp;</td>
                <td rowspan="2" align="center" style="font-size:16px;line-height:24px;color:#ffffff;"><img src="https://s3.amazonaws.com/tackle.io-misc/gcp_marketplace_logo_wht.png" width="80" height="80" alt="GCP Marketplace" style="max-width:60px;vertical-align:middle;border:0;"></td>
                <td height="28" width="30" style="border-bottom:2px solid #ffffff;">&nbsp;</td></tr>
            <tr><td height="30">&nbsp;</td><td height="30">&nbsp;</td></tr>
          </tbody></table>
          <p style="margin-top:0px;margin-bottom:0px;font-size:10px;line-height:10px;">&nbsp;</p>
          <h2 style="font-family:Helvetica,Arial,sans-serif;font-weight:bold;margin-top:0px;margin-bottom:8px;font-size:32px;line-height:40px;">New GCP Order</h2>
          <p style="margin-top:0px;margin-bottom:0px;font-size:18px;">{prod}</p>
        </td>
      </tr></tbody></table>
    </td>
  </tr></tbody></table>
  <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation"><tbody><tr>
    <td align="center" style="background-color:#dfe1e6;padding-left:8px;padding-right:8px;">
      <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody><tr>
        <td align="left" style="font-family:Helvetica,Arial,sans-serif;font-size:16px;line-height:22px;background-color:#ffffff;color:#505f79;padding-left:60px;padding-right:60px;padding-top:20px;padding-bottom:16px;">
          <p style="margin-top:0px;margin-bottom:0px;">Congratulations on the new order from <strong>{co}</strong>. The details of this order are:</p>
        </td>
      </tr></tbody></table>
    </td>
  </tr></tbody></table>
  <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation"><tbody><tr>
    <td align="center" style="background-color:#dfe1e6;padding-left:8px;padding-right:8px;">
      <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody><tr>
        <td align="center" style="font-family:Helvetica,Arial,sans-serif;font-size:16px;line-height:22px;background-color:#ffffff;color:#505f79;padding-left:60px;padding-right:60px;padding-top:16px;padding-bottom:8px;">
          <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody><tr>
            <td align="center" style="background-color:#ebecf0;color:#505f79;padding-left:60px;padding-right:60px;padding-top:16px;padding-bottom:16px;">
              <h4 style="font-family:Helvetica,Arial,sans-serif;font-weight:bold;margin-top:0px;margin-bottom:8px;color:#505f79;font-size:18px;line-height:23px;">Buyer ID (External Account ID)</h4>
              <p style="margin-top:0px;margin-bottom:0px;">{acc}</p>
            </td>
          </tr></tbody></table>
        </td>
      </tr></tbody></table>
    </td>
  </tr></tbody></table>
  <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation"><tbody><tr>
    <td align="center" style="background-color:#dfe1e6;padding-left:8px;padding-right:8px;">
      <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody><tr>
        <td align="center" style="font-size:0;vertical-align:top;background-color:#ffffff;padding-left:60px;padding-right:60px;padding-bottom:16px;">
          <div style="display:inline-block;vertical-align:top;width:100%;max-width:632px;"><div>
            <table width="100%" role="presentation" cellspacing="0" cellpadding="0" border="0"><tbody><tr>
              <td align="center" style="background-color:#ebecf0;color:#505f79;padding-left:24px;padding-right:24px;padding-top:20px;padding-bottom:20px;">
                <table width="100%" role="presentation" cellspacing="0" cellpadding="0" border="0"><tbody>
                  <tr><td width="45%" align="left"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#505f79;"><strong>Order Date/Time</strong></p></td><td width="10%">&nbsp;</td><td width="45%" align="left"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#505f79;"><strong>Offer ID (Quote External Name)</strong></p></td></tr>
                  <tr><td width="45%" align="left"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#505f79;">{st}</p></td><td width="10%">&nbsp;</td><td width="45%" align="left"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#505f79;">{oid}</p></td></tr>
                  <tr><td><p style="margin:0;font-size:10px;line-height:10px;color:#505f79;">&nbsp;</p></td><td>&nbsp;</td><td><p style="margin:0;font-size:10px;line-height:10px;color:#505f79;">&nbsp;</p></td></tr>
                  <tr><td width="45%" align="left"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#505f79;"><strong>Product ID (Solution ID)</strong></p></td><td>&nbsp;</td><td></td></tr>
                  <tr><td width="45%" align="left"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#505f79;">{pid}</p></td><td>&nbsp;</td><td></td></tr>
                  <tr><td><p style="margin:0;font-size:10px;line-height:10px;color:#505f79;">&nbsp;</p></td><td>&nbsp;</td><td><p style="margin:0;font-size:10px;line-height:10px;color:#505f79;">&nbsp;</p></td></tr>
                  <tr><td width="45%" align="left"><p style="font-family:Helvetica,Arial,sans-serif;margin-top:10px;margin-bottom:0px;font-size:14px;line-height:21px;color:#505f79;"><strong>Service End Date</strong></p></td><td>&nbsp;</td><td></td></tr>
                  <tr><td align="left"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#505f79;">{en}</p></td><td>&nbsp;</td><td></td></tr>
                </tbody></table>
              </td>
            </tr></tbody></table>
          </div></div>
        </td>
      </tr></tbody></table>
    </td>
  </tr></tbody></table>
  <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation"><tbody><tr>
    <td align="center" style="background-color:#dfe1e6;padding-left:8px;padding-right:8px;">
      <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody><tr>
        <td align="Center" style="font-family:Helvetica,Arial,sans-serif;font-size:16px;line-height:22px;background-color:#ffffff;color:#505f79;padding-left:60px;padding-right:60px;padding-top:16px;padding-bottom:0px;">
          <h4 style="font-family:Helvetica,Arial,sans-serif;font-weight:bold;margin-top:0px;margin-bottom:12px;color:#242b3d;font-size:20px;line-height:26px;">Entitlements</h4>
        </td>
      </tr></tbody></table>
    </td>
  </tr></tbody></table>
  <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation"><tbody><tr>
    <td align="center" style="background-color:#dfe1e6;padding-left:8px;padding-right:8px;">
      <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody><tr>
        <td align="center" style="font-size:0;vertical-align:top;background-color:#ffffff;padding-left:120px;padding-right:120px;padding-bottom:16px;">
          <div style="display:inline-block;vertical-align:top;width:100%;max-width:632px;"><div>
            <table width="100%" role="presentation" cellspacing="0" cellpadding="0" border="0"><tbody><tr>
              <td align="left" style="background-color:#253858;padding-left:24px;padding-right:24px;padding-top:20px;padding-bottom:20px;">
                <table width="100%" role="presentation" cellspacing="0" cellpadding="0" border="0"><tbody>
                  <tr><td width="25%" align="left" style="padding-top:6px;"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#ffffff;"><strong>SKU</strong></p></td><td width="10%">&nbsp;</td><td width="65%" align="right" style="padding-top:6px;"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#ffffff;word-break:break-all;">{sku}</p></td></tr>
                  <tr><td width="25%" align="left" style="padding-top:6px;"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#ffffff;"><strong>Entitlement ID</strong></p></td><td width="10%">&nbsp;</td><td width="65%" align="right" style="padding-top:6px;"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#ffffff;word-break:break-all;">{eid}</p></td></tr>
                </tbody></table>
              </td>
            </tr></tbody></table>
          </div></div>
        </td>
      </tr></tbody></table>
    </td>
  </tr></tbody></table>
  <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation"><tbody><tr>
    <td align="center" style="background-color:#dfe1e6;padding-left:8px;padding-right:8px;">
      <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody><tr>
        <td align="Center" style="background-color:#ffffff;color:#505f79;padding-left:60px;padding-right:60px;padding-top:40px;padding-bottom:0px;">
          <h4 style="font-family:Helvetica,Arial,sans-serif;font-weight:bold;margin-top:0px;margin-bottom:0px;color:#242b3d;font-size:20px;line-height:26px;">Registration Details</h4>
        </td>
      </tr></tbody></table>
    </td>
  </tr></tbody></table>
  <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation"><tbody><tr>
    <td align="center" style="background-color:#dfe1e6;padding-left:8px;padding-right:8px;">
      <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody><tr>
        <td class="o_re o_bg-white o_px o_pb-md" align="center" style="font-size:0;vertical-align:top;background-color:#ffffff;padding-left:120px;padding-right:58px;padding-top:24px;padding-bottom:40px;">
          <!--[if mso]><table cellspacing="0" cellpadding="0" border="0" role="presentation"><tbody><tr><td width="480" align="center" valign="top" style="padding:0px 8px;"><![endif]-->
          <div class="o_col o_col-full" style="display:inline-block;vertical-align:top;width:100%;max-width:100%;">
            <div class="o_px-xs" style="padding-left:0px;padding-right:0px;">
              <table width="100%" role="presentation" cellspacing="0" cellpadding="0" border="0"><tbody>
                <tr><td width="45%" class="o_pt-xs" align="left"><p class="o_sans o_text-xs o_text-white" style="font-family:Helvetica,Arial,sans-serif;margin-top:0px;margin-bottom:0px;font-size:14px;line-height:22px;color:#505f79;word-break:break-all;"><strong>Company</strong></p><p class="o_sans o_text-xs o_text-white" style="font-family:Helvetica,Arial,sans-serif;margin-top:0px;margin-bottom:0px;font-size:14px;line-height:22px;color:#505f79;word-break:break-all;">{co}</p></td></tr>
                <tr><td class="o_bg-white" style="font-size:12px;line-height:12px;height:12px;background-color:#ffffff;">&nbsp; </td></tr>
                <tr><td width="45%" class="o_pt-xs" align="left"><p class="o_sans o_text-xs o_text-white" style="font-family:Helvetica,Arial,sans-serif;margin-top:0px;margin-bottom:0px;font-size:14px;line-height:22px;color:#505f79;word-break:break-all;"><strong>Full Name</strong></p><p class="o_sans o_text-xs o_text-white" style="font-family:Helvetica,Arial,sans-serif;margin-top:0px;margin-bottom:0px;font-size:14px;line-height:22px;color:#505f79;word-break:break-all;">{fn}</p></td></tr>
                <tr><td class="o_bg-white" style="font-size:12px;line-height:12px;height:12px;background-color:#ffffff;">&nbsp; </td></tr>
                <tr><td width="45%" class="o_pt-xs" align="left"><p class="o_sans o_text-xs o_text-white" style="font-family:Helvetica,Arial,sans-serif;margin-top:0px;margin-bottom:0px;font-size:14px;line-height:22px;color:#505f79;word-break:break-all;"><strong>Email Address</strong></p><p class="o_sans o_text-xs o_text-white" style="font-family:Helvetica,Arial,sans-serif;margin-top:0px;margin-bottom:0px;font-size:14px;line-height:22px;color:#505f79;word-break:break-all;">{em}</p></td></tr>
                <tr><td class="o_bg-white" style="font-size:12px;line-height:12px;height:12px;background-color:#ffffff;">&nbsp; </td></tr>
                <tr><td width="45%" class="o_pt-xs" align="left"><p class="o_sans o_text-xs o_text-white" style="font-family:Helvetica,Arial,sans-serif;margin-top:0px;margin-bottom:0px;font-size:14px;line-height:22px;color:#505f79;word-break:break-all;"><strong>Contact Phone Number</strong></p><p class="o_sans o_text-xs o_text-white" style="font-family:Helvetica,Arial,sans-serif;margin-top:0px;margin-bottom:0px;font-size:14px;line-height:22px;color:#505f79;word-break:break-all;">{ph}</p></td></tr>
                <tr><td class="o_bg-white" style="font-size:12px;line-height:12px;height:12px;background-color:#ffffff;">&nbsp; </td></tr>
                <tr><td width="45%" class="o_pt-xs" align="left"><p class="o_sans o_text-xs o_text-white" style="font-family:Helvetica,Arial,sans-serif;margin-top:0px;margin-bottom:0px;font-size:14px;line-height:22px;color:#505f79;word-break:break-all;"><strong>Company Website</strong></p><p class="o_sans o_text-xs o_text-white" style="font-family:Helvetica,Arial,sans-serif;margin-top:0px;margin-bottom:0px;font-size:14px;line-height:22px;color:#505f79;word-break:break-all;">{web}</p></td></tr>
                <tr><td class="o_bg-white" style="font-size:12px;line-height:12px;height:12px;background-color:#ffffff;">&nbsp; </td></tr>
                <tr><td width="45%" class="o_pt-xs" align="left"><p class="o_sans o_text-xs o_text-white" style="font-family:Helvetica,Arial,sans-serif;margin-top:0px;margin-bottom:0px;font-size:14px;line-height:22px;color:#505f79;word-break:break-all;"><strong>Billing Address (Include Full Address)</strong></p><p class="o_sans o_text-xs o_text-white" style="font-family:Helvetica,Arial,sans-serif;margin-top:0px;margin-bottom:0px;font-size:14px;line-height:22px;color:#505f79;word-break:break-all;">{bill}</p></td></tr>
                <tr><td class="o_bg-white" style="font-size:12px;line-height:12px;height:12px;background-color:#ffffff;">&nbsp; </td></tr>
              </tbody></table>
            </div>
          </div>
          <!--[if mso]></td></tr></table><![endif]-->
        </td>
      </tr></tbody></table>
    </td>
  </tr></tbody></table>
  <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation"><tbody><tr>
    <td align="center" style="background-color:#dfe1e6;padding-left:8px;padding-right:8px;">
      <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody>
        <tr><td align="left" style="font-family:Helvetica,Arial,sans-serif;font-size:16px;line-height:22px;background-color:#ffffff;color:#505f79;padding-left:60px;padding-right:60px;padding-top:0px;padding-bottom:0px;"><p style="margin:0;">Please contact them directly to confirm the purchase and gather any additional information. It&#8217;s time to deploy some software!</p></td></tr>
        <tr><td style="font-size:24px;line-height:24px;height:24px;background-color:#ffffff;">&nbsp;</td></tr>
        <tr><td align="left" style="font-family:Helvetica,Arial,sans-serif;font-size:16px;line-height:22px;background-color:#ffffff;color:#505f79;padding-left:60px;padding-right:60px;"><p style="margin:0;"><strong>Cheers!</strong></p></td></tr>
        <tr><td align="left" style="font-family:Helvetica,Arial,sans-serif;font-size:16px;line-height:22px;background-color:#ffffff;color:#505f79;padding-left:60px;padding-right:60px;"><p style="margin:0;">Team Tackle</p></td></tr>
      </tbody></table>
    </td>
  </tr></tbody></table>
  <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation"><tbody><tr>
    <td align="center" style="background-color:#dfe1e6;padding-left:8px;padding-right:8px;"><table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody><tr><td style="font-size:60px;line-height:60px;height:60px;background-color:#ffffff;">&nbsp;</td></tr></tbody></table></td>
  </tr></tbody></table>
  <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation"><tbody><tr>
    <td align="center" style="background-color:#dfe1e6;padding-left:8px;padding-right:8px;padding-bottom:32px;">
      <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody>
        <tr><td style="font-size:8px;line-height:12px;height:8px;font-family:Helvetica,Arial,sans-serif;background-color:#ffffff;border-radius:0px 0px 12px 12px;">&nbsp;</td></tr>
        <tr><td align="center" style="font-family:Helvetica,Arial,sans-serif;font-size:14px;line-height:21px;color:#82899a;padding-left:24px;padding-right:24px;padding-top:32px;padding-bottom:32px;">
          <p style="margin-top:0px;margin-bottom:16px;"><a href="https://tackle.io/" style="text-decoration:none;color:#126DE5;"><img src="https://s3.amazonaws.com/tackle.io-misc/tackle-logo.png" width="80" height="24" alt="Tackle.io" style="max-width:80px;vertical-align:middle;border:0;"></a></p>
          <p style="margin-top:0px;margin-bottom:16px;">&#169;2025 Tackle.io</p>
          <p style="margin-top:0px;margin-bottom:8px;">218 N Capitol Blvd.<br>Boise, ID 83702</p>
        </td></tr>
      </tbody></table>
      <div style="font-size:40px;line-height:40px;height:40px;">&nbsp;</div>
    </td>
  </tr></tbody></table>
</div>"""
    return subject, html

def render_gcp_partner(d):
    co = d['companyName']; acc = d['accountId']; prod = d['productName']
    pid = d['productId']; oid = d['offerId']; eid = d['agreementId']
    st = d['startDate']; en = d['endDate']; sku = d['offerName']
    ifd = d.get('isFutureDated',''); ssd = d.get('serviceStartDate','')
    rpid = d.get('resellerPlanId','')
    fn = d.get('gcpFullName',''); em = d.get('gcpEmail','')
    ph = d.get('gcpPhone',''); web = d.get('gcpWebsite',''); bill = d.get('gcpBilling','')
    subject = f"[Cloud Marketplace] New GCP Order of {prod} from {co}"
    # GCP Partner uses same Tackle template structure as Direct but with extra key values
    # and different registration field order: Company, Website, Billing, Full Name, Email, Phone
    html = f"""<div style="background-color:#dfe1e6;font-family:Helvetica,Arial,sans-serif;padding:0;font-size:0;line-height:0;">
  <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation"><tbody><tr>
    <td align="center" style="background-color:#dfe1e6;padding-left:8px;padding-right:8px;padding-top:32px;">
      <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody><tr>
        <td align="center" style="font-size:0;vertical-align:top;background-color:#253858;border-radius:12px 12px 0px 0px;padding-left:16px;padding-right:16px;padding-bottom:24px;">
          <div style="display:inline-block;vertical-align:top;width:100%;max-width:200px;">
            <div style="font-size:24px;line-height:24px;height:24px;">&nbsp;</div>
            <div style="font-family:Helvetica,Arial,sans-serif;font-size:16px;line-height:24px;text-align:center;padding-left:8px;padding-right:8px;">
              <p style="margin:0;"><a href="https://tackle.io/" style="text-decoration:none;color:#FFFFFF;"><img src="https://s3.amazonaws.com/tackle.io-misc/tackle-logo-light.png" width="80" height="24" alt="Tackle.io" style="max-width:80px;vertical-align:middle;border:0;"></a></p>
            </div>
          </div>
        </td>
      </tr></tbody></table>
    </td>
  </tr></tbody></table>
  <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation"><tbody><tr>
    <td align="center" style="background-color:#dfe1e6;padding-left:8px;padding-right:8px;">
      <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody><tr>
        <td align="center" style="font-family:Helvetica,Arial,sans-serif;font-size:19px;line-height:28px;background-color:#0052cc;color:#ffffff;padding-left:24px;padding-right:24px;padding-top:50px;padding-bottom:60px;">
          <table role="presentation" cellspacing="0" cellpadding="0" border="0"><tbody>
            <tr><td height="28" width="30" style="border-bottom:2px solid #ffffff;">&nbsp;</td>
                <td rowspan="2" align="center" style="color:#ffffff;"><img src="https://s3.amazonaws.com/tackle.io-misc/gcp_marketplace_logo_wht.png" width="80" height="80" alt="GCP Marketplace" style="max-width:60px;vertical-align:middle;border:0;"></td>
                <td height="28" width="30" style="border-bottom:2px solid #ffffff;">&nbsp;</td></tr>
            <tr><td height="30">&nbsp;</td><td height="30">&nbsp;</td></tr>
          </tbody></table>
          <p style="margin:0;font-size:10px;line-height:10px;">&nbsp;</p>
          <h2 style="font-family:Helvetica,Arial,sans-serif;font-weight:bold;margin:0 0 8px;font-size:32px;line-height:40px;">New GCP Order</h2>
          <p style="margin:0;font-size:18px;">{prod}</p>
        </td>
      </tr></tbody></table>
    </td>
  </tr></tbody></table>
  <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation"><tbody><tr><td align="center" style="background-color:#dfe1e6;padding-left:8px;padding-right:8px;"><table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody><tr><td align="left" style="font-family:Helvetica,Arial,sans-serif;font-size:16px;line-height:22px;background-color:#ffffff;color:#505f79;padding-left:60px;padding-right:60px;padding-top:20px;padding-bottom:16px;"><p style="margin:0;">Congratulations on the new order from <strong>{co}</strong>. The details of this order are:</p></td></tr></tbody></table></td></tr></tbody></table>
  <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation"><tbody><tr><td align="center" style="background-color:#dfe1e6;padding-left:8px;padding-right:8px;"><table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody><tr><td align="center" style="background-color:#ffffff;color:#505f79;padding-left:60px;padding-right:60px;padding-top:16px;padding-bottom:8px;"><table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody><tr><td align="center" style="background-color:#ebecf0;color:#505f79;padding-left:60px;padding-right:60px;padding-top:16px;padding-bottom:16px;"><h4 style="font-family:Helvetica,Arial,sans-serif;font-weight:bold;margin-top:0px;margin-bottom:8px;color:#505f79;font-size:18px;line-height:23px;">Buyer ID (External Account ID)</h4><p style="margin:0;">{acc}</p></td></tr></tbody></table></td></tr></tbody></table></td></tr></tbody></table>
  <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation"><tbody><tr><td align="center" style="background-color:#dfe1e6;padding-left:8px;padding-right:8px;"><table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody><tr>
    <td align="center" style="font-size:0;vertical-align:top;background-color:#ffffff;padding-left:60px;padding-right:60px;padding-bottom:16px;">
      <div style="display:inline-block;vertical-align:top;width:100%;max-width:632px;"><div>
        <table width="100%" role="presentation" cellspacing="0" cellpadding="0" border="0"><tbody><tr>
          <td align="center" style="background-color:#ebecf0;color:#505f79;padding-left:24px;padding-right:24px;padding-top:20px;padding-bottom:20px;">
            <table width="100%" role="presentation" cellspacing="0" cellpadding="0" border="0"><tbody>
              <tr><td width="45%" align="left"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#505f79;"><strong>Order Date/Time</strong></p></td><td width="10%">&nbsp;</td><td width="45%" align="left"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#505f79;"><strong>Offer ID (Quote External Name)</strong></p></td></tr>
              <tr><td width="45%" align="left"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#505f79;">{st}</p></td><td width="10%">&nbsp;</td><td width="45%" align="left"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#505f79;">{oid}</p></td></tr>
              <tr><td><p style="margin:0;font-size:10px;line-height:10px;">&nbsp;</p></td><td>&nbsp;</td><td><p style="margin:0;font-size:10px;line-height:10px;">&nbsp;</p></td></tr>
              <tr><td width="45%" align="left"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#505f79;"><strong>Product ID (Solution ID)</strong></p></td><td>&nbsp;</td><td></td></tr>
              <tr><td width="45%" align="left"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#505f79;">{pid}</p></td><td>&nbsp;</td><td></td></tr>
              <tr><td><p style="margin:0;font-size:10px;line-height:10px;">&nbsp;</p></td><td>&nbsp;</td><td><p style="margin:0;font-size:10px;line-height:10px;">&nbsp;</p></td></tr>
              <tr><td width="45%" align="left"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#505f79;"><strong>Is it future dated offer</strong></p></td><td>&nbsp;</td><td width="45%" align="left"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#505f79;"><strong>Service Start Date</strong></p></td></tr>
              <tr><td width="45%" align="left"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#505f79;">{ifd}</p></td><td>&nbsp;</td><td width="45%" align="left"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#505f79;">{ssd}</p></td></tr>
              <tr><td width="45%" align="left"><p style="font-family:Helvetica,Arial,sans-serif;margin-top:10px;margin-bottom:0px;font-size:14px;line-height:21px;color:#505f79;"><strong>Service End Date</strong></p></td><td>&nbsp;</td><td width="45%" align="left"><p style="font-family:Helvetica,Arial,sans-serif;margin-top:10px;margin-bottom:0px;font-size:14px;line-height:21px;color:#505f79;"><strong>Reseller Private Offer Plan ID</strong></p></td></tr>
              <tr><td align="left"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#505f79;">{en}</p></td><td>&nbsp;</td><td width="45%" align="left"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#505f79;">{rpid}</p></td></tr>
            </tbody></table>
          </td>
        </tr></tbody></table>
      </div></div>
    </td>
  </tr></tbody></table></td></tr></tbody></table>
  <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation"><tbody><tr><td align="center" style="background-color:#dfe1e6;padding-left:8px;padding-right:8px;"><table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody><tr><td align="Center" style="background-color:#ffffff;color:#505f79;padding-left:60px;padding-right:60px;padding-top:16px;padding-bottom:0px;"><h4 style="font-family:Helvetica,Arial,sans-serif;font-weight:bold;margin:0 0 12px;color:#242b3d;font-size:20px;line-height:26px;">Entitlements</h4></td></tr></tbody></table></td></tr></tbody></table>
  <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation"><tbody><tr><td align="center" style="background-color:#dfe1e6;padding-left:8px;padding-right:8px;"><table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody><tr><td align="center" style="font-size:0;vertical-align:top;background-color:#ffffff;padding-left:120px;padding-right:120px;padding-bottom:16px;"><div style="display:inline-block;vertical-align:top;width:100%;max-width:632px;"><div><table width="100%" role="presentation" cellspacing="0" cellpadding="0" border="0"><tbody><tr><td align="left" style="background-color:#253858;padding-left:24px;padding-right:24px;padding-top:20px;padding-bottom:20px;"><table width="100%" role="presentation" cellspacing="0" cellpadding="0" border="0"><tbody><tr><td width="25%" align="left" style="padding-top:6px;"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#ffffff;"><strong>SKU</strong></p></td><td width="10%">&nbsp;</td><td width="65%" align="right" style="padding-top:6px;"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#ffffff;word-break:break-all;">{sku}</p></td></tr><tr><td width="25%" align="left" style="padding-top:6px;"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#ffffff;"><strong>Entitlement ID</strong></p></td><td width="10%">&nbsp;</td><td width="65%" align="right" style="padding-top:6px;"><p style="font-family:Helvetica,Arial,sans-serif;margin:0;font-size:14px;line-height:21px;color:#ffffff;word-break:break-all;">{eid}</p></td></tr></tbody></table></td></tr></tbody></table></div></div></td></tr></tbody></table></td></tr></tbody></table>
  <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation"><tbody><tr><td align="center" style="background-color:#dfe1e6;padding-left:8px;padding-right:8px;"><table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody><tr><td align="Center" style="background-color:#ffffff;color:#505f79;padding-left:60px;padding-right:60px;padding-top:40px;padding-bottom:0px;"><h4 style="font-family:Helvetica,Arial,sans-serif;font-weight:bold;margin:0;color:#242b3d;font-size:20px;line-height:26px;">Registration Details</h4></td></tr></tbody></table></td></tr></tbody></table>
  <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation"><tbody><tr><td align="center" style="background-color:#dfe1e6;padding-left:8px;padding-right:8px;"><table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody><tr><td align="center" style="font-size:0;vertical-align:top;background-color:#ffffff;padding-left:120px;padding-right:58px;padding-top:24px;padding-bottom:40px;"><div style="display:inline-block;vertical-align:top;width:100%;max-width:100%;"><div><table width="100%" role="presentation" cellspacing="0" cellpadding="0" border="0"><tbody>
    <tr><td>{_p('','<strong>Company</strong>')}<br>{_p('',co)}</td></tr><tr><td style="font-size:12px;line-height:12px;height:12px;background-color:#ffffff;">&nbsp;</td></tr>
    <tr><td>{_p('','<strong>Company Website</strong>')}<br>{_p('',web)}</td></tr><tr><td style="font-size:12px;line-height:12px;height:12px;background-color:#ffffff;">&nbsp;</td></tr>
    <tr><td>{_p('','<strong>Billing Address (Include Full Address)</strong>')}<br>{_p('',bill)}</td></tr><tr><td style="font-size:12px;line-height:12px;height:12px;background-color:#ffffff;">&nbsp;</td></tr>
    <tr><td>{_p('','<strong>Full Name</strong>')}<br>{_p('',fn)}</td></tr><tr><td style="font-size:12px;line-height:12px;height:12px;background-color:#ffffff;">&nbsp;</td></tr>
    <tr><td>{_p('','<strong>Email Address</strong>')}<br>{_p('',em)}</td></tr><tr><td style="font-size:12px;line-height:12px;height:12px;background-color:#ffffff;">&nbsp;</td></tr>
    <tr><td>{_p('','<strong>Contact Phone Number</strong>')}<br>{_p('',ph)}</td></tr><tr><td style="font-size:12px;line-height:12px;height:12px;background-color:#ffffff;">&nbsp;</td></tr>
  </tbody></table></div></div></td></tr></tbody></table></td></tr></tbody></table>
  <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation"><tbody><tr><td align="center" style="background-color:#dfe1e6;padding-left:8px;padding-right:8px;"><table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody><tr><td align="left" style="font-family:Helvetica,Arial,sans-serif;font-size:16px;line-height:22px;background-color:#ffffff;color:#505f79;padding-left:60px;padding-right:60px;"><p style="margin:0;">Please contact them directly to confirm the purchase and gather any additional information. It&#8217;s time to deploy some software!</p></td></tr><tr><td style="font-size:24px;line-height:24px;height:24px;background-color:#ffffff;">&nbsp;</td></tr><tr><td align="left" style="font-family:Helvetica,Arial,sans-serif;font-size:16px;line-height:22px;background-color:#ffffff;color:#505f79;padding-left:60px;padding-right:60px;"><p style="margin:0;"><strong>Cheers!</strong></p></td></tr><tr><td align="left" style="font-family:Helvetica,Arial,sans-serif;font-size:16px;line-height:22px;background-color:#ffffff;color:#505f79;padding-left:60px;padding-right:60px;"><p style="margin:0;">Team Tackle</p></td></tr></tbody></table></td></tr></tbody></table>
  <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation"><tbody><tr><td align="center" style="background-color:#dfe1e6;padding-left:8px;padding-right:8px;"><table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody><tr><td style="font-size:60px;line-height:60px;height:60px;background-color:#ffffff;">&nbsp;</td></tr></tbody></table></td></tr></tbody></table>
  <table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation"><tbody><tr><td align="center" style="background-color:#dfe1e6;padding-left:8px;padding-right:8px;padding-bottom:32px;"><table width="100%" cellspacing="0" cellpadding="0" border="0" role="presentation" style="max-width:632px;margin:0 auto;"><tbody><tr><td style="font-size:8px;line-height:12px;height:8px;background-color:#ffffff;border-radius:0px 0px 12px 12px;">&nbsp;</td></tr><tr><td align="center" style="font-family:Helvetica,Arial,sans-serif;font-size:14px;line-height:21px;color:#82899a;padding-left:24px;padding-right:24px;padding-top:32px;padding-bottom:32px;"><p style="margin:0 0 16px;"><a href="https://tackle.io/" style="color:#126DE5;"><img src="https://s3.amazonaws.com/tackle.io-misc/tackle-logo.png" width="80" height="24" alt="Tackle.io" style="max-width:80px;vertical-align:middle;border:0;"></a></p><p style="margin:0 0 16px;">&#169;2025 Tackle.io</p><p style="margin:0 0 8px;">218 N Capitol Blvd.<br>Boise, ID 83702</p></td></tr></tbody></table><div style="font-size:40px;line-height:40px;height:40px;">&nbsp;</div></td></tr></tbody></table>
</div>"""
    return subject, html

def render_azure_direct(d):
    subject = "[Cloud Marketplace] Your customer bought products in your private offer"
    on = d['offerName']; oid = d['offerId']; pn = d['productName']
    pl = d.get('azurePlan',''); pt = d.get('azureProductType','')
    html = f"""<div style="font-family:Segoe UI,SegoeUI,Roboto,'Helvetica Neue',Arial,sans-serif;background-color:#ffffff;max-width:640px;margin:auto;border:1px solid #e0e0e0;">
  <div style="padding:20px 24px;border-bottom:1px solid #f0f0f5;"><img height="21" src="https://images.ecomm.microsoft.com/cdn/mediahandler/azure-emails-templates/production/shared/images/templates/shared/images/logos/microsoft-logo-2x.png" alt="Microsoft header logo" style="height:21px;width:auto;display:block;border:0;"></div>
  <div style="padding:24px;background-color:#ffffff;font-size:14px;line-height:22px;color:#323130;border-bottom:1px solid rgba(201,201,207,.35);">
    <h1 style="margin-top:0;line-height:36px;margin-bottom:16px;color:#11100F;font-size:28px;font-weight:600;font-family:Segoe UI Semibold,SegoeUISemibold,Segoe UI,SegoeUI,Roboto,'Helvetica Neue',Arial,sans-serif;">Your customer completed a purchase in your private offer</h1>
    <p style="margin-top:0;font-weight:400;line-height:20px;font-size:14px;margin-bottom:12px;">Your customer has purchased products with your private offer. It can take up to <b style="font-weight:600;">five hours</b> for the purchase status to be updated in Partner Center on the Private Offers dashboard.</p>
    <table style="color:#323130;border-collapse:collapse;margin-bottom:16px;width:100%;font-size:14px;"><tbody style="border-top:1px solid #c9c9c9;border-bottom:1px solid #c9c9c9;">
      <tr><th style="font-family:Segoe UI Semibold,Segoe UI,Roboto,'Helvetica Neue',Arial,sans-serif;font-weight:400;white-space:nowrap;text-align:left;padding:8px 8px 8px 0;vertical-align:top;">Private offer:</th><td style="padding:8px 8px 8px 0;width:100%;vertical-align:top;font-weight:400;"><a href="https://partner.microsoft.com/en-us/dashboard/commercial-marketplace/private-offers/{oid}" style="color:#0078D4;text-decoration:none;word-break:keep-all;">{on}</a></td></tr>
      <tr><th style="font-family:Segoe UI Semibold,Segoe UI,Roboto,'Helvetica Neue',Arial,sans-serif;font-weight:400;white-space:nowrap;border-top:1px solid #c9c9c9;text-align:left;padding:8px 8px 8px 0;vertical-align:top;">Private offer ID:</th><td style="border-top:1px solid #c9c9c9;padding:8px 8px 8px 0;width:100%;vertical-align:top;font-weight:400;">{oid}</td></tr>
    </tbody></table>
    <h3 style="font-weight:600;margin:12px 0;font-family:Segoe UI Semibold,SegoeUISemibold,Segoe UI,SegoeUI,Roboto,'Helvetica Neue',Arial,sans-serif;line-height:28px;font-size:20px;">Products bought</h3>
    <table style="color:#323130;border-collapse:collapse;width:100%;margin-bottom:16px;font-size:14px;">
      <thead><tr><th style="font-family:Segoe UI Semibold,Segoe UI,Roboto,'Helvetica Neue',Arial,sans-serif;font-weight:400;border-bottom:2px solid #c9c9c9;text-align:left;padding:8px 8px 8px 0;vertical-align:top;">Product</th><th style="font-family:Segoe UI Semibold,Segoe UI,Roboto,'Helvetica Neue',Arial,sans-serif;font-weight:400;border-bottom:2px solid #c9c9c9;text-align:left;padding:8px 8px 8px 0;vertical-align:top;">Plan</th><th style="font-family:Segoe UI Semibold,Segoe UI,Roboto,'Helvetica Neue',Arial,sans-serif;font-weight:400;border-bottom:2px solid #c9c9c9;text-align:left;padding:8px 8px 8px 0;vertical-align:top;">Product type</th></tr></thead>
      <tbody><tr><td style="border-bottom:1px solid #c9c9c9;padding:8px 8px 8px 0;vertical-align:top;font-weight:400;">{pn}</td><td style="border-bottom:1px solid #c9c9c9;padding:8px 8px 8px 0;vertical-align:top;font-weight:400;">{pl}</td><td style="border-bottom:1px solid #c9c9c9;padding:8px 8px 8px 0;vertical-align:top;font-weight:400;">{pt}</td></tr></tbody>
    </table>
    <p style="margin-top:0;font-weight:400;line-height:20px;font-size:14px;margin-bottom:12px;">You don't need to take any action. If you have questions, please <a href="https://aka.ms/marketplacepublishersupport" style="color:#0078D4;text-decoration:none;">contact us</a>.</p>
  </div>
  <div style="padding:23px 24px 24px;font-size:12px;background-color:#F0F0F0;color:#484644;line-height:16px;"><p style="color:#484644;font-weight:400;font-size:12px;line-height:16px;margin:0 0 12px;"><a href="https://go.microsoft.com/fwlink/?LinkId=521839" style="color:#484644;text-decoration:underline;">Privacy Statement</a></p><p style="color:#484644;font-weight:400;margin:8px 0 12px;font-size:12px;line-height:16px;">Microsoft Corporation, One Microsoft Way, Redmond, WA 98052</p><img height="21" src="https://images.ecomm.microsoft.com/cdn/mediahandler/azure-emails-templates/production/shared/images/templates/shared/images/logos/microsoft-logo-2x.png" alt="Microsoft footer logo" style="height:21px;display:block;border:0;"></div>
</div>"""
    return subject, html

def render_azure_partner(d):
    subject = "[Cloud Marketplace] Your customer bought products in your private offer"
    on = d['offerName']; oid = d['offerId']; pn = d['productName']
    pl = d.get('azurePlan',''); pt = d.get('azureProductType','')
    tid = d.get('azureTenantId',''); aid = d.get('azureAssetId','')
    cs = d.get('azureContractStart',''); ce = d.get('azureContractEnd','')
    html = f"""<div style="font-family:Segoe UI,SegoeUI,Roboto,'Helvetica Neue',Arial,sans-serif;background-color:#ffffff;max-width:640px;margin:auto;border:1px solid #e0e0e0;">
  <div style="padding:20px 24px;border-bottom:1px solid #f0f0f5;"><img height="21" src="https://images.ecomm.microsoft.com/cdn/mediahandler/azure-emails-templates/production/shared/images/templates/shared/images/logos/microsoft-logo-2x.png" alt="Microsoft header logo" style="height:21px;width:auto;display:block;border:0;"></div>
  <div style="padding:24px;background-color:#ffffff;font-size:14px;line-height:22px;color:#323130;border-bottom:1px solid rgba(201,201,207,.35);">
    <h1 style="margin-top:0;line-height:36px;margin-bottom:16px;color:#11100F;font-size:28px;font-weight:600;font-family:Segoe UI Semibold,SegoeUISemibold,Segoe UI,SegoeUI,Roboto,'Helvetica Neue',Arial,sans-serif;">Your customer completed a purchase in your private offer</h1>
    <p style="margin-top:0;font-weight:400;line-height:20px;font-size:14px;margin-bottom:12px;">Your customer has purchased products with your private offer. It can take up to <b style="font-weight:600;">five hours</b> for the purchase status to be updated in Partner Center on the Private Offers dashboard.</p>
    <table style="color:#323130;border-collapse:collapse;margin-bottom:16px;width:100%;font-size:14px;"><tbody style="border-top:1px solid #c9c9c9;border-bottom:1px solid #c9c9c9;">
      <tr><th style="font-family:Segoe UI Semibold,Segoe UI,Roboto,'Helvetica Neue',Arial,sans-serif;font-weight:400;white-space:nowrap;text-align:left;padding:8px 8px 8px 0;vertical-align:top;">Private offer:</th><td style="padding:8px 8px 8px 0;width:100%;vertical-align:top;font-weight:400;"><a href="https://partner.microsoft.com/en-us/dashboard/commercial-marketplace/private-offers/{oid}" style="color:#0078D4;text-decoration:none;word-break:keep-all;">{on}</a></td></tr>
      <tr><th style="font-family:Segoe UI Semibold,Segoe UI,Roboto,'Helvetica Neue',Arial,sans-serif;font-weight:400;white-space:nowrap;border-top:1px solid #c9c9c9;text-align:left;padding:8px 8px 8px 0;vertical-align:top;">Private offer ID:</th><td style="border-top:1px solid #c9c9c9;padding:8px 8px 8px 0;width:100%;vertical-align:top;font-weight:400;">{oid}</td></tr>
    </tbody></table>
    <h3 style="font-weight:600;margin:12px 0;font-family:Segoe UI Semibold,SegoeUISemibold,Segoe UI,SegoeUI,Roboto,'Helvetica Neue',Arial,sans-serif;line-height:28px;font-size:20px;">Products bought</h3>
    <table style="color:#323130;border-collapse:collapse;width:100%;margin-bottom:16px;font-size:14px;">
      <thead><tr><th style="font-family:Segoe UI Semibold,Segoe UI,Roboto,'Helvetica Neue',Arial,sans-serif;font-weight:400;border-bottom:2px solid #c9c9c9;text-align:left;padding:8px 8px 8px 0;vertical-align:top;">Product</th><th style="font-family:Segoe UI Semibold,Segoe UI,Roboto,'Helvetica Neue',Arial,sans-serif;font-weight:400;border-bottom:2px solid #c9c9c9;text-align:left;padding:8px 8px 8px 0;vertical-align:top;">Plan</th><th style="font-family:Segoe UI Semibold,Segoe UI,Roboto,'Helvetica Neue',Arial,sans-serif;font-weight:400;border-bottom:2px solid #c9c9c9;text-align:left;padding:8px 8px 8px 0;vertical-align:top;">Product type</th></tr></thead>
      <tbody><tr><td style="border-bottom:1px solid #c9c9c9;padding:8px 8px 8px 0;vertical-align:top;font-weight:400;">{pn}</td><td style="border-bottom:1px solid #c9c9c9;padding:8px 8px 8px 0;vertical-align:top;font-weight:400;">{pl}</td><td style="border-bottom:1px solid #c9c9c9;padding:8px 8px 8px 0;vertical-align:top;font-weight:400;">{pt}</td></tr></tbody>
    </table>
    <p style="margin-top:0;font-weight:400;line-height:20px;font-size:14px;margin-bottom:12px;">You don't need to take any action. If you have questions, please <a href="https://aka.ms/marketplacepublishersupport" style="color:#0078D4;text-decoration:none;">contact us</a>.</p>
    <h3 style="font-weight:600;margin:12px 0;font-family:Segoe UI Semibold,SegoeUISemibold,Segoe UI,SegoeUI,Roboto,'Helvetica Neue',Arial,sans-serif;line-height:28px;font-size:20px;">Subscription details</h3>
    <table style="color:#323130;border-collapse:collapse;width:100%;margin-bottom:16px;font-size:14px;">
      <thead><tr><th style="font-family:Segoe UI Semibold,Segoe UI,Roboto,'Helvetica Neue',Arial,sans-serif;font-weight:400;border-bottom:2px solid #c9c9c9;text-align:left;padding:8px 8px 8px 0;vertical-align:top;">Tenant ID</th><th style="font-family:Segoe UI Semibold,Segoe UI,Roboto,'Helvetica Neue',Arial,sans-serif;font-weight:400;border-bottom:2px solid #c9c9c9;text-align:left;padding:8px 8px 8px 0;vertical-align:top;">Asset ID</th><th style="font-family:Segoe UI Semibold,Segoe UI,Roboto,'Helvetica Neue',Arial,sans-serif;font-weight:400;border-bottom:2px solid #c9c9c9;text-align:left;padding:8px 8px 8px 0;vertical-align:top;">Contract start dates</th><th style="font-family:Segoe UI Semibold,Segoe UI,Roboto,'Helvetica Neue',Arial,sans-serif;font-weight:400;border-bottom:2px solid #c9c9c9;text-align:left;padding:8px 8px 8px 0;vertical-align:top;">Contract end date</th></tr></thead>
      <tbody><tr><td style="border-bottom:1px solid #c9c9c9;padding:8px 8px 8px 0;vertical-align:top;font-weight:400;">{tid}</td><td style="border-bottom:1px solid #c9c9c9;padding:8px 8px 8px 0;vertical-align:top;font-weight:400;">{aid}</td><td style="border-bottom:1px solid #c9c9c9;padding:8px 8px 8px 0;vertical-align:top;font-weight:400;">{cs}</td><td style="border-bottom:1px solid #c9c9c9;padding:8px 8px 8px 0;vertical-align:top;font-weight:400;">{ce}</td></tr></tbody>
    </table>
  </div>
  <div style="padding:23px 24px 24px;font-size:12px;background-color:#F0F0F0;color:#484644;line-height:16px;"><p style="color:#484644;font-weight:400;font-size:12px;line-height:16px;margin:0 0 12px;"><a href="https://go.microsoft.com/fwlink/?LinkId=521839" style="color:#484644;text-decoration:underline;">Privacy Statement</a></p><p style="color:#484644;font-weight:400;margin:8px 0 12px;font-size:12px;line-height:16px;">Microsoft Corporation, One Microsoft Way, Redmond, WA 98052</p><img height="21" src="https://images.ecomm.microsoft.com/cdn/mediahandler/azure-emails-templates/production/shared/images/templates/shared/images/logos/microsoft-logo-2x.png" alt="Microsoft footer logo" style="height:21px;display:block;border:0;"></div>
</div>"""
    return subject, html

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--provider', required=True)
    ap.add_argument('--quote',    required=True)
    ap.add_argument('--data',     default='')
    args = ap.parse_args()

    p = args.provider.upper().replace('-','_').replace(' ','_')
    q = args.quote if args.quote.startswith('Q-') else f'Q-{args.quote}'
    d = decode_data(args.data) if args.data else {}

    if p in ('AWS', 'AWS_DIRECT'):
        subj, html = render_aws(q, d)
    elif p == 'AWS_PARTNER':
        subj, html = render_aws_partner(q, d)
    elif p == 'GCP_DIRECT':
        subj, html = render_gcp_direct(d)
    elif p == 'GCP_PARTNER':
        subj, html = render_gcp_partner(d)
    elif p in ('AZURE', 'AZURE_DIRECT', 'MFST_AZURE_DIRECT'):
        subj, html = render_azure_direct(d)
    elif p in ('AZURE_PARTNER', 'AZURE_FLEX', 'MFST_AZURE_FLEX'):
        subj, html = render_azure_partner(d)
    else:
        print(json.dumps({"error": f"Unknown provider: {args.provider}"}))
        sys.exit(1)

    print(json.dumps({"subject": subj, "html": html}))

if __name__ == '__main__':
    main()
