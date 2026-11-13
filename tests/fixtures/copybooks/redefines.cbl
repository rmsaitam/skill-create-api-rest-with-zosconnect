       01  PAYMENT-RECORD.
           05  CARD-DATA.
               10  CARD-NUMBER      PIC X(16).
           05  BANK-DATA REDEFINES CARD-DATA.
               10  BANK-ACCOUNT     PIC X(20).
