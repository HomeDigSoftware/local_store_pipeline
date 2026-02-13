{{ config(materialized='view') }}

-- Primary sales transactions from Verifon Retail 360 POS
-- Source: Documents (5,733 rows), DocumentLines (10,294 rows), ReceiptLines (8,331 rows)
-- Clean and standardize Documents + DocumentLines + ReceiptLines for sales analytics


SELECT
    d.Document_ID,

    concat (d.RecordingDate , ' ',RIGHT('00' + CAST((d.PrintTime / 60) / 60 AS VARCHAR(2)), 2)
			+ ':' +
	RIGHT('00' + CAST((d.PrintTime / 60) % 60 AS VARCHAR(2)), 2) ) AS ReceiptDateTime,
    CAST(d.RecordingDate AS DATE) AS ReceiptDate,
    
	
	RIGHT('00' + CAST((d.PrintTime / 60) / 60 AS VARCHAR(2)), 2)
			+ ':' +
	RIGHT('00' + CAST((d.PrintTime / 60) % 60 AS VARCHAR(2)), 2)
     AS Sale_Time,
    d.DocumentType,

    dl.Item_ID,
    dl.Details AS ItemName,

    dl.ItemsQty AS Quantity,

    dl.TotalPerLine_IncVAT AS LineTotal_IncVAT,
    d.GeneralTotalIncludeVAT AS ReceiptTotal_IncVAT,

	r.PaymentType ,
	case
		when r.PaymentType = 3 then 1
		else 0
	end as IsCredit,

	r.CreditCardType,
	cct.CardDesc ,
    CASE 
        WHEN d.GeneralTotalIncludeVAT < 0 THEN 1
        ELSE 0
    END AS IsReturn,

    d.s__sequence AS SourceDocumentSequence
FROM {{ source('store_data', 'Documents') }} d
JOIN {{ source('store_data', 'DocumentLines') }} dl
  ON d.Document_ID = dl.Document_ID
LEFT JOIN {{ source('store_data', 'ReceiptLines') }} r on r.Receipt_ID = d.Document_ID 
LEFT join {{ source('store_data', 'CreditCardsTypes') }} cct on r.CreditCardType = cct.CreditCardType
WHERE r.AccountNumber_moreInfo not like '2'

