**Ticket: PRDOPS-1422 & PRDOPS-1759**  
**Title**: **GLYNT \- Update System to accept Arrow ECS CA shipping Terms to stop Stage PO from not progressing**

**\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#**  
**Scenario 1: Verify StagePO should be success when the Shipping terms field is updated with “EXW” value and the distributor should be updated as “**Arrow ECS Canada**”**

Create the Opportunity with **“**Arrow ECS Canada” disti  
****

Create the Quote and make it as Primary and approved  


Create the Stage PO and update the “Shipping Terms” field as “EXW” value in the Stage PO and validate the record  


**Expected Outcome:**  
  
**Actual Outcome:**  


Order should be created with updated value and order should be booked to NS successfully  


\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#  
**Scenario 2: Verify StagePO should be success when the Shipping terms field is updated with “FCA Origin” value and the distributor should be updated as “**Arrow ECS Canada**”**

Create the Opportunity with **“**Arrow ECS Canada” disti  


Create the Quote as Primary and approved  


Create the Stage PO and update the “Shipping Terms” field as “FCA Origin” value in the Stage PO and validate the record



**Expected Outcome:**  
Stage PO should be success and order should be created  when the Shipping terms field as “FCA Origin” when the disti is “Arrow ECS canada”

  
**Actual outcome:**  
  
  


\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#  
**Scenario 3: Verify StagePO should be success when the Shipping terms field is updated with “DAP” value and the distributor should be updated as “**Arrow ECS Canada**”**

Create the Opportunity with “Arrow ECS Canada” disti  
  
Create the Quote as Primary and approved  


Create the Stage PO and update the “Shipping Terms” field as “DAP” value in the Stage PO and validate the record



**Expected Outcome:** Stage PO should be failed and PO-08: Missing or Incorrect Shipping Terms (FCA) external validation error must **not** be triggered  and order should be created when the Shipping terms field as “DAP” when the disti is “Arrow ECS canada”  
**Actual outcome:**   
****

**\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#**  
**Scenario 4:  Verify StagePO should be success when the Shipping terms field is updated with “DDP” value and the distributor should be updated as “**Arrow ECS Canada**”**

Create the Opportunity with “Arrow ECS Canada” disti

****

Create the Quote as Primary and approved

Create the Stage PO and update the “Shipping Terms” field as “DDP” value in the Stage PO and validate the record  


**Expected Outcome:**  
Stage PO should be failed and PO-08: Missing or Incorrect Shipping Terms external validation error must not be triggered  and order should be created when the Shipping terms field as “DAP” when the disti is “Arrow ECS canada”

**Actual Outcome:**  
****  
****

**\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#**  
**Scenario 5: Verify StagePO should be success when the Shipping terms field is updated with “Other” value and the distributor should be updated as “**Arrow ECS Canada**”**

Create the Opportunity with “Arrow ECS Canada” dis**ti**

****

Create the Quote as Primary and approved  


Create the Stage PO and update the “Shipping Terms” field as “Other” value in the Stage PO and validate the record  


Stage PO should be failed and PO-08: Missing or Incorrect Shipping Terms (FCA) external validation error must not be triggered  and order should be created when the Shipping terms field as “DAP” when the disti is “Arrow ECS canada”  
****

\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#  
**Scenario 6: Verify StagePO should be success when the Shipping terms field is updated with “FCA Origin” value and the distributor should be updated as “Arrow ECS North America”**

Create the Opportunity with “Arrow ECS North America” disti  


Create the Quote as Primary and approved  


Create the Stage PO and update the “Shipping Terms” field as “FCA Origin” value in the Stage PO and validate the record  


**Expected Outcome:** Stage PO should be success without any issue and order should be created  
**Actual Outcome:**





\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#  
**Scenario 7: Verify StagePO should be success when the Shipping terms field is updated with “EXW” value and the distributor should be updated as “Arrow ECS North America”**

Create the Opportunity with “Arrow ECS America” disti  
****

Create the Quote as Primary and approved  


Create the Stage PO and update the “Shipping Terms” field as “EXW” value in the Stage PO and validate the record



**Expected Outcome:**   
****

**Actual Outcome:**  
****

**\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#**  
**Scenario 8: Verify StagePO should be Failed  when the Shipping terms field is updated with “EXW” value and the distributor should be updated as “Arrow ECS North America”**

Create the Opportunity with “Arrow ECS America” disti

  
Create the Quote as Primary and approved  


Create the Stage PO and update the “Shipping Terms” field as “EXW” value in the Stage PO and validate the record



Expected Outcome:   
  
Actual Outcome:  
  


\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#  
Scenario 9: Verify StagePO should be success when the Shipping terms field is updated with “FCA Origin” value and the distributor should be updated as “Ingram Micro US”  


  
Create the Stage PO and update the “Shipping Terms” field as “FCA Origin ” value in the Stage PO and validate the record  


**Expected Outcome:**  
Stage PO should be success without any issue and order should be created

**Actual Outcome:**  


\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#  
Scenario 10: Verify StagePO should be Failed  when the Shipping terms field is updated with “EXW” value and the distributor should be updated as “Ingram Micro US”  


Create the Quote as Primary and approved  


Create the Stage PO and update the “Shipping Terms” field as “EXW” value in the Stage PO and validate the record



**Expected Outcome:**  
****

**Actual Outcome:**  


\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#  
Scenario 11: Verify StagePO should be successful when the Shipping terms field is updated with “FCA Origin” value and the distributor should be updated as “[Carahsoft Technology Corp.](https://rubrikinc--rbkqa.sandbox.lightning.force.com/lightning/r/Account/0014000001o5BNXAA2/view)”

Create the Opportunity with “[Carahsoft Technology Corp.](https://rubrikinc--rbkqa.sandbox.lightning.force.com/lightning/r/Account/0014000001o5BNXAA2/view)” disti  
  
Create the Quote as Primary and approved  
  
Create the Stage PO and update the “Shipping Terms” field as “FCA Origin” value in the Stage PO and validate the record  


Expected Outcome:  
Stage PO should be success without any issue and order should be created

Actual Outcome:  
  


\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#  
Scenario 12: Verify StagePO should be Failed when the Shipping terms field is updated with “EXW” value and the distributor should be updated as “[Carahsoft Technology Corp.](https://rubrikinc--rbkqa.sandbox.lightning.force.com/lightning/r/Account/0014000001o5BNXAA2/view) ”



Create the Quote as Primary and approved  


Create the Stage PO and update the “Shipping Terms” field as “EXW” value in the Stage PO and validate the record



**Expected Outcome:**  
****  
**Actual Outcome:**  
****

**\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#**  
**Scenario 13: Verify Stage PO should be success when the Shipping terms field is updated with “FCA Origin” value and the distributor should be updated as “**[Exclusive Networks (United Kingdom)](https://rubrikinc--rbkqa.sandbox.lightning.force.com/lightning/r/Account/0014000001gDigqAAC/view) **”**

Create the Opportunity with “[Exclusive Networks (United Kingdom)](https://rubrikinc--rbkqa.sandbox.lightning.force.com/lightning/r/Account/0014000001gDigqAAC/view)” disti

****

Create the Quote as Primary and approved  


Create the Stage PO and update the “Shipping Terms” field as “FCA Origin” value in the Stage PO and validate the record  


**Expected Outcome:**  
Stage PO should be success without any issue and order should be created  
**Actual Outcome:**  
  


\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#  
**Scenario 14: Verify Stage PO should be success when the Shipping terms field is updated with “FCA Origin” value and the distributor should be updated as “**[Exclusive Networks (United Kingdom)](https://rubrikinc--rbkqa.sandbox.lightning.force.com/lightning/r/Account/0014000001gDigqAAC/view) **”**

Create the Opportunity with “[Exclusive Networks (United Kingdom)](https://rubrikinc--rbkqa.sandbox.lightning.force.com/lightning/r/Account/0014000001gDigqAAC/view)” disti

****

Create the Quote as Primary and approved  


Create the Stage PO and update the “Shipping Terms” field as “EXW” value in the Stage PO and validate the record  
****

**Expected Outcome:**  
****  
**Actual Outcome:**  
****

**\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#**  
**Scenario 15: Verify StagePO should be success when the Shipping terms field is updated with “FCA Origin” value and the distributor should be updated as “**[Exclusive Networks (Spain)](https://rubrikinc--rbkqa.sandbox.lightning.force.com/lightning/r/Account/0014000001ia8ujAAA/view) **”**

**Create the Opportunity with “**[Exclusive Networks (Spain)](https://rubrikinc--rbkqa.sandbox.lightning.force.com/lightning/r/Account/0014000001ia8ujAAA/view)**” disti**  
****  
Create the Quote as Primary and approved  


Create the Stage PO and update the “Shipping Terms” field as “FCA Origin” value in the Stage PO and validate the record  
****

**Expected Outcome:**  
Stage PO should be success without any issue and order should be created  
**Actual outcome:**  
****

**\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#**  
**Scenario 16: Verify StagePO should be success when the Shipping terms field is updated with “EXW” value and the distributor should be updated as “**[Exclusive Networks (Spain)](https://rubrikinc--rbkqa.sandbox.lightning.force.com/lightning/r/Account/0014000001ia8ujAAA/view) **”**

Create the Opportunity with “[Exclusive Networks (Spain)](https://rubrikinc--rbkqa.sandbox.lightning.force.com/lightning/r/Account/0014000001ia8ujAAA/view)a” disti  


Create the Quote as Primary and approved  


Create the Stage PO and update the “Shipping Terms” field as “EXW” value in the Stage PO and validate the record.



**Expected Outcome:**  
****

**Actual Outcome:**  
  


\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#  
Scenario 17:  Verify StagePO should be success when the Shipping terms field is updated with “FCA” value and the distributor should be updated as “Arrow ECS Canada”

JSON:  


Stage PO:  


**Expected Outcome:**  
****  
**Actual Outcome:**  
****  
****

**Order: **

**\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#**

Scenario 18:  Verify StagePO should be success when the Shipping terms field is updated with “Origin”(Starting with Upparcase/Capital) value and the distributor should be updated as “Arrow ECS Canada”

JSON: 

Expected Outcome: 

Actual Outcome:  
Stage PO:

****

**Order:**  
****  
****

**\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#**  
Scenario 19:  Verify StagePO should be success when the Shipping terms field is updated with “origin”(Starting with a lowercase letter) value and the distributor should be updated as “Arrow ECS Canada”

JSON:  
****

Expected Outcome: 

**Actual Outcome:**  
****

**Order:**  
****

**\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#**  
Scenario 20:  Verify StagePO should be success when the Shipping terms field is updated with “Origin” value and the distributor should be updated as “Exclusive Networks (Spain)”

JSON:

****

**Expected Outcome:**  
****  
**Actual Outcome:**  
****

**Order:**  
****



























































































































