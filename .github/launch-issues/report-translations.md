# Add Chinese and Japanese service-report UI translations

The public demo now has English/Korean service-report UI. The Chinese/Japanese README guides should lead to UI that their readers can navigate.

Scope: faultdebug/service_report_view.py and test/service_report_test.py. Add zh-CN/ja presentation labels using the existing UI-before-data translation boundary.

Acceptance:
- Existing en/ko behavior stays compatible.
- Captured reason/source strings and report JSON stay verbatim.
- Report controls, keyboard labels, theme and print labels are translated.
- Escaped captured strings remain escaped; unsupported languages still fail explicitly.

This is UI work; do not change evidence assessments or native ABI.
