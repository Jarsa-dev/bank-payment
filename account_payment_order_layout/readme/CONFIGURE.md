To configure this module you need to:

- Enter Account/Configuration/Management/Payment Mode Layout.
- Crate a new layout.
- Add one line for each field that the bank requires.
- If header or footer is neccesary, add it in the corresponding tab.
- Enter Account/Configuration/Management/Payment Mode.
- Create or select a payment mode.
- Select the layout created in the previous step.

Optional settings:

- In the layout, *Line Ending* sets the characters that separate the
  records of the file (LF or CRLF).
- In each line, *Strict Length* raises an error when the value is longer
  than its length instead of truncating it. Use it on accounts and
  amounts, where a truncated value is a wrong value.
- Non ASCII characters are transliterated per value (e.g. "Ñ" becomes
  "N") before padding, so the fixed positions are kept.
