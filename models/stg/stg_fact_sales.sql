{{ config(materialized='view') }}

-- Primary sales transactions from Verifon Retail 360 POS
-- Source: Fact_Sales table (14,946 records identified in data discovery)


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
    d.Document_ID as sale_id,

    concat (d.RecordingDate , ' ',RIGHT('00' + CAST((d.PrintTime / 60) / 60 AS VARCHAR(2)), 2)
			+ ':' +
	RIGHT('00' + CAST((d.PrintTime / 60) % 60 AS VARCHAR(2)), 2) ) AS sale_datetime,
    CAST(d.RecordingDate AS DATE) AS sale_date,
    
	
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



-- Primary sales transactions from Verifon Retail 360 POS
-- Clean and standardize Documents + DocumentLines + ReceiptLines for sales analytics
-- Source: Documents (5,733 rows), DocumentLines (10,294 rows), ReceiptLines (8,331 rows)
{# 
with sales_transactions as (
    select
        d.Document_ID as transaction_id,
        d.s__sequence as source_document_sequence,
        
        concat(
            d.RecordingDate, 
            ' ',
            right('00' + cast((d.PrintTime / 60) / 60 as varchar(2)), 2)
            + ':' +
            right('00' + cast((d.PrintTime / 60) % 60 as varchar(2)), 2)
        ) as transaction_datetime,
        
        cast(d.RecordingDate as date) as transaction_date,
        
        right('00' + cast((d.PrintTime / 60) / 60 as varchar(2)), 2)
        + ':' +
        right('00' + cast((d.PrintTime / 60) % 60 as varchar(2)), 2)
        as transaction_time,
        
        d.DocumentType as document_type_code,
        
        dl.Item_ID as product_id,
        dl.Details as product_name,
        
        dl.ItemsQty as quantity_sold,
        cast(dl.TotalPerLine_IncVAT as decimal(10,2)) as line_total_amount_incl_vat,
        cast(d.GeneralTotalIncludeVAT as decimal(10,2)) as receipt_total_amount_incl_vat,
        
        r.PaymentType as payment_type_code,
        case 
            when r.PaymentType = 3 then true
            else false 
        end as is_credit_payment,
        
        r.CreditCardType as credit_card_type_code,
        
        case 
            when d.GeneralTotalIncludeVAT < 0 then true
            else false 
        end as is_return_transaction,
        
        current_timestamp as dbt_loaded_at,
        'stg_fact_sales' as dbt_source_model
        
    from {{ source('store_data', 'Documents') }} d
    join {{ source('store_data', 'DocumentLines') }} dl
        on d.Document_ID = dl.Document_ID
    left join {{ source('store_data', 'ReceiptLines') }} r 
        on r.Receipt_ID = d.Document_ID 
    WHERE r.AccountNumber_moreInfo not like '2' 
)

select * from sales_transactions #}