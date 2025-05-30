## Manual Testing Guide: Calendar Event Dragging, Snapping, and Resource ID

**Objective:** To manually verify the functionality of event dragging, resizing, slot snapping, and resource identification in the "My Calendar" feature.

**Tester:** Human QA

**Date of Test:** YYYY-MM-DD

**Version/Branch:** (Specify code version or branch if applicable)

---

**I. Testing Environment Setup:**

1.  **Deployment:** Ensure the latest code changes (`static/js/calendar.js` and any related backend changes) are deployed to the testing environment.
2.  **Browser & Dev Tools:** Use a modern web browser (e.g., Chrome, Firefox). Open the browser's developer console (usually F12) to monitor JavaScript logs and any errors. Pay close attention to messages from `static/js/calendar.js`.
3.  **User Login:** Log in as a designated test user.
4.  **Navigation:** Navigate to the "My Calendar" page.
5.  **Test Data - User's Bookings:**
    *   Before starting, ensure the test user has a diverse set of bookings. If not, create them. This may involve multiple resources if the user has access to book more than one.
    *   **Variety of Bookings Needed:**
        *   **Resource 1 (R1):**
            *   Day 1 (e.g., Next Monday): Morning booking (08:00-12:00) - "R1 Morning Only"
            *   Day 2 (e.g., Next Tuesday): Afternoon booking (13:00-17:00) - "R1 Afternoon Only"
            *   Day 3 (e.g., Next Wednesday): Full-day booking (08:00-17:00) - "R1 Full Day"
            *   Day 4 (e.g., Next Thursday): Empty (no bookings for R1).
            *   Day 5 (e.g., Next Friday):
                *   Morning booking (08:00-12:00) - "R1 Day5 Morning"
                *   Afternoon booking (13:00-17:00) - "R1 Day5 Afternoon" (Day is fully booked by R1)
            *   Day 6 (e.g., Following Monday):
                *   Booking from 10:00-11:00 - "R1 Partial Morning"
                *   Booking from 14:00-15:00 - "R1 Partial Afternoon"
            *   Day 7 (e.g., Following Tuesday):
                *   (If DB allows custom times not aligned to slots, create one like 09:00-11:00 - "R1 Custom Short" or 10:00-15:00 "R1 Custom Long". If not, skip 'Custom' event type tests or simulate by noting an existing event's duration if it's non-standard).
        *   **Resource 2 (R2) (Optional, if user can book multiple):**
            *   Day 1 (Next Monday): Morning booking (08:00-12:00) - "R2 Morning"
            *   Day 4 (Next Thursday): Full-day booking (08:00-17:00) - "R2 Full Day"

---

**II. Test Cases:**

**A. Resource Identification:**

*   **Goal:** Ensure `resourceId` is always correctly identified for the event being manipulated.
*   **Procedure:** For every drag/resize operation performed in sections B and C:
    1.  Before starting the drag/resize, note the event's title and original resource.
    2.  Open the developer console.
    3.  Perform the drag/resize.
    4.  Observe the console for logs:
        *   `console.log('customEventDrop: event object:', ...);` or `console.log('customEventResize: event object:', ...);`
        *   `console.log('customEventDrop: retrieved resourceId:', resourceId);` or `console.log('customEventResize: retrieved resourceId:', resourceId);`
*   **Test A1: Validate `resourceId` Log**
    *   **Expected:** The `resourceId` in the log should be a valid numerical or string ID corresponding to the resource the event belongs to. It should not be `null` or `undefined`.
    *   **Pass/Fail:**
    *   **Notes (if fail):**
*   **Test A2: "Could not identify resource" Alert**
    *   **Expected:** The alert "Could not identify the resource for this booking. Operation cancelled." should NOT appear during any valid operation. If it does, it indicates a failure in `resourceId` retrieval.
    *   **Pass/Fail:**
    *   **Notes (if fail, describe event and circumstances):**

**B. Event Dragging and Snapping Logic (Strict Slots):**

*   **B1: Dragging Morning Event (e.g., "R1 Morning Only" from Day 1, 08:00-12:00)**
    *   **B1.1: To Empty Morning Slot**
        *   Action: Drag "R1 Morning Only" to Day 4's morning (target 08:00-12:00 area).
        *   Expected: Event snaps to Day 4, 08:00-12:00. Booking saves. Console shows logs indicating successful placement in the morning slot.
        *   Pass/Fail:
        *   Console Logs:
    *   **B1.2: To Occupied Morning, Free Afternoon**
        *   Action: Drag "R1 Morning Only" to Day 6 (where "R1 Partial Morning" 10:00-11:00 exists, so morning slot 08-12 is NOT completely free), but Day 6 afternoon (13:00-17:00) is free (after "R1 Partial Afternoon" 14-15, so 13-17 is NOT completely free. Let's assume Day 2 afternoon IS free for this test). Drag "R1 Morning Only" to Day 2 (where "R1 Afternoon Only" exists, so afternoon is booked, but morning is free).
        *   Correction: Drag "R1 Morning Only" (Day 1, 08-12) to a new date (e.g., Day X) where Day X has a booking from 09:00-10:00 (making morning slot occupied) but Day X's 13:00-17:00 slot is completely empty.
        *   Expected: Event snaps to Day X, 13:00-17:00. Booking saves. Console logs show morning was checked, found occupied, then afternoon was checked, found free, and event placed there.
        *   Pass/Fail:
        *   Console Logs:
    *   **B1.3: To Fully Occupied Day**
        *   Action: Drag "R1 Morning Only" to Day 5 (fully booked by "R1 Day5 Morning" and "R1 Day5 Afternoon").
        *   Expected: Event reverts to its original position. Alert: "The selected time slot is not available or does not align with standard booking slots (Morning, Afternoon, Full Day). Reverting." Console logs show checks for morning and afternoon slots, both found unavailable, and revert decision.
        *   Pass/Fail:
        *   Console Logs:
    *   **B1.4: To Occupied Morning, Partially Occupied Afternoon**
        *   Action: Drag "R1 Morning Only" to Day 6 (morning slot 08-12 is occupied by "R1 Partial Morning" 10-11; afternoon slot 13-17 is partially occupied by "R1 Partial Afternoon" 14-15).
        *   Expected: Event reverts. Alert. Console logs show morning slot check fails, afternoon slot check fails (due to partial booking).
        *   Pass/Fail:
        *   Console Logs:

*   **B2: Dragging Afternoon Event (e.g., "R1 Afternoon Only" from Day 2, 13:00-17:00)**
    *   **B2.1: To Empty Afternoon Slot**
        *   Action: Drag "R1 Afternoon Only" to Day 4's afternoon (target 13:00-17:00 area).
        *   Expected: Snaps to Day 4, 13:00-17:00. Saved.
        *   Pass/Fail:
        *   Console Logs:
    *   **B2.2: To Occupied Afternoon, Free Morning**
        *   Action: Drag "R1 Afternoon Only" to a new date (e.g., Day Y) where Day Y has a booking from 14:00-15:00 (afternoon occupied), but Day Y's 08:00-12:00 slot is completely empty.
        *   Expected: Snaps to Day Y, 08:00-12:00. Saved.
        *   Pass/Fail:
        *   Console Logs:
    *   **B2.3: To Fully Occupied Day**
        *   Action: Drag "R1 Afternoon Only" to Day 5.
        *   Expected: Reverts. Alert.
        *   Pass/Fail:
        *   Console Logs:

*   **B3: Dragging Full-Day Event (e.g., "R1 Full Day" from Day 3, 08:00-17:00)**
    *   **B3.1: To Empty Day**
        *   Action: Drag "R1 Full Day" to Day 4.
        *   Expected: Snaps to Day 4, 08:00-17:00. Saved.
        *   Pass/Fail:
        *   Console Logs:
    *   **B3.2: To Partially Occupied Day**
        *   Action: Drag "R1 Full Day" to Day 6 (has partial bookings).
        *   Expected: Reverts. Alert. Console logs show full-day slot check fails.
        *   Pass/Fail:
        *   Console Logs:

*   **B4: Dragging 'Custom' Duration Event (Use "R1 Custom Short" 09:00-11:00 or "R1 Custom Long" 10:00-15:00 if created. Otherwise, this test might be less relevant or needs adaptation).**
    *   **B4.1: Custom Short (~2hr) to Empty Date**
        *   Action: Drag "R1 Custom Short" (e.g., Day 7, 09:00-11:00) to Day 4 (empty).
        *   Expected: Snaps to Day 4 Morning slot (08:00-12:00). Saved. Console logs show it identified as custom, then fit into morning.
        *   Pass/Fail:
        *   Console Logs:
    *   **B4.2: Custom Short (~2hr) to Occupied Morning, Free Afternoon on New Date**
        *   Action: Drag "R1 Custom Short" to a new date (Day Z) where morning 08-12 is booked, but afternoon 13-17 is free.
        *   Expected: Snaps to Day Z Afternoon slot (13:00-17:00). Saved.
        *   Pass/Fail:
        *   Console Logs:
    *   **B4.3: Custom Long (~5hr, e.g., 10:00-15:00) to Empty Date**
        *   Action: Drag "R1 Custom Long" to Day 4 (empty).
        *   Expected: Snaps to Day 4 Full Day slot (08:00-17:00). Saved. Console logs show it identified as custom, too long for half-day, then fit into full-day.
        *   Pass/Fail:
        *   Console Logs:
    *   **B4.4: Custom Event to Partially Occupied Day (No Full Standard Slot Free)**
        *   Action: Drag "R1 Custom Short" or "R1 Custom Long" to Day 6 (partially occupied, no full standard Morning, Afternoon, or Full Day slot is completely free).
        *   Expected: Reverts. Alert.
        *   Pass/Fail:
        *   Console Logs:

*   **B5: Dragging to Create Non-Standard Time (Attempting to bypass strict snapping)**
    *   Action: Take any event (e.g., "R1 Morning Only"). Attempt to drag it to a new empty date (Day 4) but try to drop it precisely from 10:00 to 14:00 (a 4-hour slot, but not standard).
    *   Expected: The event should snap to the closest valid standard slot (likely Morning 08:00-12:00 or Afternoon 13:00-17:00 if the drop point is near one of them and it's considered a 'custom' drop by duration, or it might revert if the logic is very strict about where the drop point lands). Given the current logic, it will likely evaluate based on original event type. If original was 'morning', it will try to snap to 08-12 or 13-17. If drop point is mid-day, it should still evaluate based on available standard slots. The key is it should NOT create a 10:00-14:00 booking. It should snap to a standard slot or revert.
    *   Pass/Fail:
    *   Console Logs (observe which slot it snaps to or if it reverts):

**C. Event Resizing Logic:**

*   **C1: Resize Morning Event to Full Day**
    *   Action: Select "R1 Morning Only" (Day 1, 08:00-12:00). Drag its bottom edge to try and extend to 17:00. Ensure Day 1's afternoon (13:00-17:00) is currently free.
    *   Expected: Event resizes to 08:00-17:00. Saved. Console logs indicate successful resize to full day.
    *   Pass/Fail:
    *   Console Logs:
    *   Action (Repeat with occupied afternoon): Select "R1 Day5 Morning" (Day 5, 08:00-12:00). Day 5's afternoon is booked by "R1 Day5 Afternoon". Try to resize "R1 Day5 Morning" end time to 17:00.
    *   Expected: Resize reverts. Alert "Cannot resize to full day because the other half of the day is booked."
    *   Pass/Fail:
    *   Console Logs:

*   **C2: Resize Afternoon Event to Full Day**
    *   Action: Select "R1 Afternoon Only" (Day 2, 13:00-17:00). Drag its top edge to try and extend to 08:00. Ensure Day 2's morning (08:00-12:00) is currently free.
    *   Expected: Event resizes to 08:00-17:00. Saved.
    *   Pass/Fail:
    *   Console Logs:
    *   Action (Repeat with occupied morning): Select "R1 Day5 Afternoon". Day 5's morning is booked. Try to resize "R1 Day5 Afternoon" start time to 08:00.
    *   Expected: Resize reverts. Alert.
    *   Pass/Fail:
    *   Console Logs:

*   **C3: Invalid Resizes (Not forming a standard slot)**
    *   Action: Take "R1 Morning Only" (08:00-12:00). Attempt to resize its end time to 14:00 (results in 08:00-14:00, not a standard slot).
    *   Expected: Resize reverts. Alert "Invalid resize. Bookings can only be full day, morning, or afternoon, or extended from half to full if available. Reverting."
    *   Pass/Fail:
    *   Console Logs:
    *   Action: Take "R1 Full Day" (08:00-17:00). Attempt to resize its end time to 15:00 (results in 08:00-15:00).
    *   Expected: Resize reverts. Alert.
    *   Pass/Fail:
    *   Console Logs:

---

**IV. Reporting:**

*   For each test case (A1, A2, B1.1, etc.):
    *   Mark: **Pass** or **Fail**.
    *   If **Fail**:
        *   **Steps to Reproduce:** Clearly list the actions taken.
        *   **Expected Behavior:** What should have happened.
        *   **Actual Behavior:** What actually happened.
        *   **Console Logs:** Copy relevant lines from the browser's developer console, especially error messages, `resourceId` logs, and decision logs from `customEventDrop` or `customEventResize`.
        *   **Screenshot (Optional but helpful):** If UI behavior is unexpected.

---

**End of Test Guide**
