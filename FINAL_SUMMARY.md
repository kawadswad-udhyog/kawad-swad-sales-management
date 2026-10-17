# What changed, in plain language

The sales app was saving a bill even when the payment or stock line failed, and the screen still said everything was saved. It now keeps that bill incomplete and the same retry finishes the missing lines instead of making a second bill.

Prices and totals are checked by the server. A bill cannot be forced through for the wrong amount, for an inactive product, or for more packets than that salesman actually has.

Stock numbers on screen use the same figures the server calculated. Invoices and reports can see the payment method and the UPI or bank reference. Closing uses India’s date, counts cash separately from UPI and bank payments, and will not silently say the cash drawer and stock matched when they did not.

Sign-in no longer accepts a password that was saved as plain text, and it no longer lets someone in just because the password list is empty. If your own login is rejected for that reason, use the password reset script in the deployment guide. There is no shared default password.

Owner and PA screens for users, the audit log, and the company dashboard are now blocked on the server, not only hidden in the menu. A PA cannot create another owner.

The production section is now actually in the app: workers and daily wages you type in, attendance, recipes you type in, daily production in kilograms, packaging into 200 g, 500 g, and 1000 g packets, and dispatch to e-commerce, retail, a salesman, wholesale, or a distributor. A dispatch is not a sale. Production cannot be approved without a recipe you have approved, and it will not approve if the raw materials are short.

## What you need to do before real use

1. Upload this project and set the environment values in the deployment guide. The backend address is no longer built into the program.
2. Keep using the development spreadsheet until you have made one test bill and one test production batch.
3. Confirm GST with your accountant. The app does not invent tax rates.
4. Enter recipes and wages yourself. The app does not guess them.
5. Reset any old plain-text password before that person can sign in.

This version was tested on this computer with fake data. It was not tested on your live spreadsheet, so it is not yet proven safe for unsupervised daily use.
