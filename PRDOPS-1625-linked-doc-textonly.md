Ticket No: PRDOPS-1625  
Title:  Re: Marketplace New OVF Process Enhancements

\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#  
Scenario 1: Verify updated OVF form checkbox verbiage is displayed correctly

User is logged into SFDC.

A valid Marketplace opportunity with an approved primary quote exists.  
![][image1]![][image2]

Click 'Send OVF' to open the OVF pop-up.  
![][image3]![][image4]![][image5]  
![][image6]![][image7]

Click on “Complete Order Verification Form” button from the email to update the details  
![][image8]

Expected Outcome: 

![][image9]  
Actual outcome:  
![][image10]  
![][image11]

AWS:  
![][image12]![][image13]![][image14]![][image15]

Email:   
Click on “Complete Order Verification Form” button from the email to update the details

![][image16]  
![][image17]  
![][image18]  
![][image19]  
![][image20]

Expected Outcome: 

![][image9]  
Actual outcome:  
![][image21]  
![][image22]

GCP: ![][image23]![][image24]

![][image25]![][image26]![][image27]

![][image28]![][image29]

Click on “Complete Order Verification Form” button from the email to update the details  
![][image30]

Expected Outcome: 

![][image9]  
Actual outcome:  
![][image31]![][image32]![][image33]![][image34]

\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#  
Scenario 2: Verify both Opportunity Owner and AE Opportunity Owner are included on OVF emails

Azure: 

Opportunity Owner:

 AE Opportunity Owner

![][image35]

Expected Outcome:  
![][image36]  
Actual Outcome:

1: Send OVF Invite Email:  
![][image37]  
2: OVF was submitted for…” – Internal submission alert:   
![][image38]

3: “Thank you for submitting your OVF…” – Acknowledgement:  
![][image39]

AWS:   
Opportunity Owner:

 AE Opportunity Owner

![][image40]

Expected Outcome:  
![][image36]  
Actual Outcome:

1: Send OVF Invite Email:  
![][image41]  
2: OVF was submitted for…” – Internal submission alert:   
![][image42]

3: “Thank you for submitting your OVF…” – Acknowledgement:  
![][image43]

GCP:

Opportunity Owner:

 AE Opportunity Owner

![][image44]

Expected Outcome:  
![][image36]  
Actual Outcome:

1: Send OVF Invite Email:  
![][image45]

2: OVF was submitted for…” – Internal submission alert:   
![][image46]

3: “Thank you for submitting your OVF…” – Acknowledgement:

![][image47]

\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#  
Scenario 3:  Verify Email Logger submission verbiage is updated for NO\_QUOTE\_NUMBER scenario 

Azure:

Send an acceptance email to the SFDC or Azure scenario

Email: 

![][image48]

Expected Outcome:  
![][image49]

Actual Outcome:

![][image50]

AWS:

Send an acceptance email to the SFDC or Azure scenario

Email: ![][image51]

Expected Outcome:  
![][image49]

Actual Outcome:

![][image52]

GCP:

Email:  
![][image53]![][image54]![][image55]![][image56]

Expected Outcome:  
![][image49]

Actual Outcome:

![][image57]![][image58]  
\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#

Scenario 4: Verify 'Send OVF' pop-up no longer contains 'Contact Name' and 'Contact Email Address' fields

User is logged into SFDC.  
2\. A valid Marketplace opportunity with an approved primary quote exists.  
![][image59]

**Expected Outcome:**  
**![][image60]**  
**Actual Outcome:**

![][image61]![][image62]

\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#  
Scenario 5: Verify 'Send OVF' pop-up displays additional instructional language

Expected Outcome:  
![][image63]

Actual Outcome:  
![][image64]

\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#  
Scenario 5: Verify Quote PDF is included in the 'Send OVF' pop-up for Sales Rep review

Expected Outcome:  
![][image65]  
Actual Outcome:  
![][image66]![][image67]![][image68]![][image69]![][image70]

\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#  
Scenario 6:  Verify 'Send OVF' button is enabled only when SFDC Quote is Approved and marked as Primary Quote

1\. Navigate to the SFDC Quote that is Approved and marked as Primary.  
![][image71]  
![][image72]

 Click the 'Send OVF' button.  
![][image73]

Confirm the OVF pop-up opens successfully.  
![][image74]![][image75]![][image76]  
\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#  
Scenario 7: Verify 'Send OVF' button is disabled when SFDC Quote is NOT Approved  
![][image77]

Expected Outcome:  If hovered, a tooltip or message indicates the quote must be approved.  
![][image78]  
Actual Outcome:![][image79]

\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#  
Scenario 8: Verify 'Send OVF' button is disabled when SFDC Quote is NOT marked as Primary Quote

 Navigate to the SFDC Quote that is approved but not primary.

![][image80]![][image81]

Expected Outcome:  
![][image82]

Actual Outcome:  
![][image83]

\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#  
Scenario 9:  Verify 'Send OVF' is blocked when no Rubrik Quote PDF has been generated

![][image84]![][image85]

Click on Send OVF button

Expected Outcome:  
![][image86]

Actual Outcome:  
![][image87]

\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#  
Scenario 10: Verify 'Send OVF' is blocked for expired Rubrik Quote

1\. User is logged into SFDC.  
2\. SFDC Quote is Approved and Primary.  
![][image88]  
3\. The associated Rubrik Quote has an expired validity date.  
![][image89]

Expected Outcome:  
![][image90]  
Actual Outcome:

![][image91]

\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#  
Scenario 11: Verify 'Send OVF' is blocked for incorrect Distributor/Partner Lookup on Rubrik Quote

Make sure the Quote has primary, approved, unexpired and PDF email should be generated  
![][image92]

The Rubrik Quote has an incorrect Distributor Lookup.  
![][image93]

Expected Outcome:  
![][image94]

Actual Outcome:

![][image95]

\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#  
Scenario 12: Verify Secondary Owner is included in OVF email recipient list when populated

Opportunity:  
![][image96]

![][image97]

Quote:  
![][image98]![][image99]  
Click 'Send OVF' to open the OVF pop-up.  
![][image3]![][image4]![][image5]  
Expected Outcome:  
![][image100]

Actual Outcome:

* **“Send OVF” – The invite:**

![][image101]

* **“OVF was submitted for…” – Internal submission alert:**

![][image102]

* **“Thank you for submitting your OVF…” – Acknowledgement:**  
  **![][image103]**  
    
  **\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#**  
    
  **Scenario 13: Verify correct Cloud Alliance BDM is included in OVF emails for Microsoft Marketplace deals**  
    
  A Microsoft Marketplace Opportunity exists with MSFT\_OCI\_Cloud\_Alliance\_BDM\_Id\_\_c populated.  
    
  ![][image104]![][image105]  
    
  Expected Outcome:  
  ![][image106]  
    
  Actual Outcome:

* **“Send OVF” – The invite:**  
  **![][image107]**  
* **“OVF was submitted for…” – Internal submission alert:**

**![][image108]**

* **“Thank you for submitting your OVF…” – Acknowledgement:**

**![][image109]**

**\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#**

**Scenario 14: Verify correct Cloud Alliance BDM is included in OVF emails for AWS/GCP Marketplace deals**

**AWS:** 

**![][image110]**

**![][image111]**

**Expected Outcome:**

**![][image112]**

**Actual Outcome:**

* **“Send OVF” – The invite:**

**![][image113]**

* **“OVF was submitted for…” – Internal submission alert:**

**![][image114]**

* **“Thank you for submitting your OVF…” – Acknowledgement:**

**![][image115]**

**GCP:**

**![][image116]**

**![][image117]**

**Expected Outcome:**

**![][image112]**

**Actual Outcome:**

* **“Send OVF” – The invite:**

**![][image118]**

* **“OVF was submitted for…” – Internal submission alert:**

**![][image119]**

* **“Thank you for submitting your OVF…” – Acknowledgement:**

**![][image120]**

**\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#**

**Scenario 15: Validate that after the OVF is submitted, a confirmation email containing the OVF inputs, a link to the submitted OVF, and an Update/Revise button is sent to all contacts listed in the 'Marketplace Offer Contacts' section.**

**.**

**![][image121]![][image122]![][image123]**

**Expected Outcome:**

**![][image124]**

**Actual Outcome:**

**“Thank you for submitting your OVF…” – Acknowledgement:**

**![][image125]![][image126]![][image127]**

The email contains a working 'Update/Revise' button/link that directs the recipient back to the submitted OVF formsite.

**![][image128]**

**Click on the button**

**![][image129]![][image130]![][image131]![][image132]![][image133]**

**\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#Scenario 16: Verify the end to end process for Azure scenario**  
User is logged into SFDC.

A valid Marketplace opportunity with an approved primary quote exists.  
![][image1]![][image2]

Click 'Send OVF' to open the OVF pop-up.  
![][image3]![][image4]![][image5]  
![][image6]![][image7]

Click on “Complete Order Verification Form” button from the email to update the details  
![][image8]

Expected Outcome: 

![][image9]  
Actual outcome:  
![][image10]  
![][image11]

Send the acceptance email for Azure order  
![][image134]

![][image135]

OVF Record:  
![][image136]

Stage PO:  
![][image137]![][image138]  
![][image139]

Order:  
![][image140]  
![][image141]

![][image142]  
![][image143]

Login to NetSuite and navigate to the Sales order  
![][image144]

![][image145]

Update the private offer ID and Order amount in the CSV sheet  
![][image146]![][image147]



















































































































































