{{ config(materialized='table') }}

-- Primary sales transactions from Verifon Retail 360 POS
-- Source: Documents (5,733 rows), DocumentLines (10,294 rows), ReceiptLines (8,331 rows)
-- Clean and standardize Documents + DocumentLines + ReceiptLines for sales analytics
-- PostgreSQL-compatible version


SELECT
    d.document_id,

    concat(
        d.recordingdate::date,
        ' ',
        LPAD(((d.printtime / 60) / 60)::text, 2, '0')
        || ':' ||
        LPAD(((d.printtime / 60) % 60)::text, 2, '0')
    ) AS receiptdatetime,

    d.recordingdate::date AS receiptdate,

    LPAD(((d.printtime / 60) / 60)::text, 2, '0')
    || ':' ||
    LPAD(((d.printtime / 60) % 60)::text, 2, '0')
    AS sale_time,

    d.documenttype,

    dl.item_id,
    dl.details AS itemname,

    dl.itemsqty AS quantity,

    dl.totalperline_incvat AS linetotal_incvat,
    d.generaltotalincludevat AS receipttotal_incvat,

    r.paymenttype,
    CASE
        WHEN r.paymenttype = 3 THEN 1
        ELSE 0
    END AS iscredit,

    r.creditcardtype,
    cct.carddesc,
    CASE
        WHEN d.generaltotalincludevat < 0 THEN 1
        ELSE 0
    END AS isreturn,

    d.s__sequence AS sourcedocumentsequence

FROM {{ source('store_data', 'documents') }} d
JOIN {{ source('store_data', 'documentlines') }} dl
    ON d.document_id = dl.document_id
LEFT JOIN {{ source('store_data', 'receiptlines') }} r
    ON r.receipt_id = d.document_id
LEFT JOIN {{ source('store_data', 'creditcardstypes') }} cct
    ON r.creditcardtype = cct.creditcardtype
WHERE r.accountnumber_moreinfo NOT LIKE '2'
