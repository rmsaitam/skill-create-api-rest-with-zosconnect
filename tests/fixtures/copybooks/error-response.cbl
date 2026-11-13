       01  ERROR-RESPONSE.
           05  ERROR-CODE           PIC X(8).
           05  ERROR-MESSAGE        PIC X(80).
           05  ERROR-COUNT          PIC 9(2) COMP.
           05 ERROR-DETAIL OCCURS 0 TO 5 DEPENDING ON ERROR-COUNT.
               10  ERROR-FIELD      PIC X(20).
               10  ERROR-REASON     PIC X(40).
