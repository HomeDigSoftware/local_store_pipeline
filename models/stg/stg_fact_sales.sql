{{ config(materialized='view') }}

-- Primary sales transactions from Verifon Retail 360 POS
-- Source: Documents (5,733 rows), DocumentLines (10,294 rows), ReceiptLines (8,331 rows)
-- Clean and standardize Documents + DocumentLines + ReceiptLines for sales analytics



        -- TODO: Replace with actual column names from Fact_Sales table
        -- Based on typical POS structure, expected columns might be:
        -- sale_id,
        -- sale_date,
        -- sale_amount,
        -- item_id,
        -- employee_id,  
        -- receipt_number,
        -- store_id,
        -- payment_type,
        -- discount_amount,
        -- tax_amount
  
SELECT
    d.Document_ID as Sale_ID,

    concat (d.RecordingDate , ' ',RIGHT('00' + CAST((d.PrintTime / 60) / 60 AS VARCHAR(2)), 2)
			+ ':' +
	RIGHT('00' + CAST((d.PrintTime / 60) % 60 AS VARCHAR(2)), 2) ) AS Sale_DateTime,
    CAST(d.RecordingDate AS DATE) AS Sale_Date,
    
	
	RIGHT('00' + CAST((d.PrintTime / 60) / 60 AS VARCHAR(2)), 2)
			+ ':' +
	RIGHT('00' + CAST((d.PrintTime / 60) % 60 AS VARCHAR(2)), 2)
     AS Sale_Time,
  --  d.DocumentType,

    dl.Details AS ItemName,
   
    dl.ItemsQty AS Quantity,
   
    dl.Item_ID,


    dl.TotalPerLine_IncVAT AS LineTotal_IncVAT,
    d.GeneralTotalIncludeVAT AS SaleTotal_IncVAT,

	r.PaymentType ,
	case
		when r.PaymentType = 3 then 1
		else 0
	end as IsCredit,

	r.CreditCardType,
    CASE 
        WHEN d.GeneralTotalIncludeVAT < 0 THEN 1
        ELSE 0
    END AS IsReturn,

    d.s__sequence AS SourceDocumentSequence
FROM Documents d
JOIN DocumentLines dl
  ON d.Document_ID = dl.Document_ID
LEFT JOIN ReceiptLines r on r.Receipt_ID = d.Document_ID 
WHERE r.AccountNumber_moreInfo not like '2'


