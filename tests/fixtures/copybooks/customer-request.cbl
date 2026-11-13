       01  CUSTOMER-REQUEST.
           05  CUSTOMER-ID          PIC 9(9).
           05  CUSTOMER-NAME        PIC X(40).
           05  CUSTOMER-TYPE        PIC X(1).
               88  TYPE-INDIVIDUAL  VALUE 'I'.
               88  TYPE-BUSINESS    VALUE 'B'.
           05  CUSTOMER-COUNT       PIC 9(3) COMP.
           05  CUSTOMER-ADDRESS     OCCURS 3 TIMES.
               10  STREET           PIC X(30).
               10  CITY             PIC X(20).
