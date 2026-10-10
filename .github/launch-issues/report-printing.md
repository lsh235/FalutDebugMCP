# Validate and improve service-report printing on A4 and Letter

The standalone service report supports Print / PDF. Review the synthetic success, payment crash and inventory timeout reports for readable paper output.

Scope: faultdebug/service_report_view.py and documented browser evidence.

Acceptance:
- Render actual reports on A4 and Letter and inspect every page.
- Long process IDs/source lines do not clip; cause headings stay with relevant content.
- Preserve incomplete/unresolved labels in the printed document.
- Keep interactive dark/light and keyboard behavior intact.
- Record tested browser, page count and screenshots; do not claim universal browser support.
