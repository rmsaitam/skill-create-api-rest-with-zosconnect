       01  CUSTOMER-RESPONSE.
           05  CUSTOMER-ID          PIC 9(9).
           05  CUSTOMER-NAME        PIC X(40).
           05  ACCOUNT-BALANCE      PIC S9(7)V99 COMP-3.
           05  ITEM-COUNT           PIC 9(3) COMP.
           05 CUSTOMER-ITEM OCCURS 0 TO 20 DEPENDING ON ITEM-COUNT.
               10  ITEM-CODE        PIC X(10).
               10  ITEM-AMOUNT      PIC 9(7)V99.
