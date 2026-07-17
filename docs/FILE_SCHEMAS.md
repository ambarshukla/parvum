# Custodial Feed File Schemas (Parvum Reference Build)

This document details the exact file schemas for the three conformed custodial formats ingested by Parvum in Phase 1: **semt.002** (ISO 20022 Holdings XML), **MT535** (SWIFT Holdings Text), and **camt.053** (ISO 20022 Cash XML).

---

## 1. semt.002 (ISO 20022 Securities Statement of Holdings)

### Namespace
`urn:iso:std:iso:20022:tech:xsd:semt.002.001.11`

### Sample File Structure
```xml
<?xml version='1.0' encoding='utf-8'?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:semt.002.001.11">
  <SctiesBalCtdyRpt>
    <StmtGnlDtls>
      <StmtId>STMT-2026-07-16-60011234</StmtId>
      <StmtDtTm>
        <Dt>2026-07-16</Dt>
      </StmtDtTm>
    </StmtGnlDtls>
    <SfkpgAcct>
      <Id>60011234</Id>
      <Nm>Growth Portfolio</Nm>
      <AcctSvcr>
        <AnyBIC>CUSTGB2LXXX</AnyBIC>
      </AcctSvcr>
      <BaseCcy>USD</BaseCcy>
    </SfkpgAcct>
    <!-- Position Block (Repeated) -->
    <BalForAcct>
      <FinInstrmId>
        <ISIN>US0378331005</ISIN>
        <Desc>APPLE INC</Desc>
      </FinInstrmId>
      <AggtBal>
        <Unit>22792</Unit>
      </AggtBal>
      <PricDtls>
        <Val Ccy="USD">253.79</Val>
        <Dt>2026-07-16</Dt>
      </PricDtls>
      <AcctBaseCcyAmts>
        <HldgVal>
          <Amt Ccy="USD">5784381.68</Amt>
        </HldgVal>
      </AcctBaseCcyAmts>
    </BalForAcct>
  </SctiesBalCtdyRpt>
</Document>
```

### Tag Dictionary & Semantics

| XML Path | Type | Optionality | Description |
|---|---|---|---|
| `/Document/SctiesBalCtdyRpt` | Element | Required | **Securities Balance Custody Report**: Core report wrapper containing statement details. |
| `.../StmtGnlDtls` | Element | Required | **Statement General Details**: General statement metadata. |
| `.../StmtGnlDtls/StmtId` | String | Required | **Statement Identifier**: Unique ID for this statement instance. |
| `.../StmtGnlDtls/StmtDtTm/Dt` | Date | Required | **Statement Date Time / Date**: The date (YYYY-MM-DD) the statement was generated. |
| `.../SfkpgAcct` | Element | Required | **Safekeeping Account**: Account and custodian information. |
| `.../SfkpgAcct/Id` | String | Required | **Identifier**: Safekeeping account number (e.g. `60011234` — opaque custodian-issued numbers; the mapping to owners is reference data). |
| `.../SfkpgAcct/Nm` | String | Optional | **Name**: Display name of the account (e.g. `Growth Portfolio`). |
| `.../SfkpgAcct/AcctSvcr/AnyBIC` | String | Optional | **Account Servicer / Any Business Identifier Code**: SWIFT BIC of the custodian bank managing the account. |
| `.../SfkpgAcct/BaseCcy` | String | Optional | **Base Currency**: Currency code of the account (3-letter ISO 4217, e.g. `USD`). |
| `.../BalForAcct` | Element | Repeating | **Balance For Account**: Individual position entry containing asset holdings. |
| `.../BalForAcct/FinInstrmId` | Element | Required | **Financial Instrument Identifier**: Wrapper for security identification. |
| `.../FinInstrmId/ISIN` | String | Conditional | **International Securities Identification Number**: 12-char global security code (e.g. `US0378331005`). |
| `.../FinInstrmId/OthrId/Id` | String | Conditional | **Other Identifier / Identifier**: Value for non-ISIN identifiers (e.g. CUSIP, SEDOL, etc.). |
| `.../FinInstrmId/OthrId/Tp` | String | Conditional | **Other Identifier / Type**: Scheme of the alternative ID (e.g., `CUSIP`, `SEDOL`, `TICKER`). |
| `.../FinInstrmId/Desc` | String | Required | **Description**: Name or description of the security (e.g. `APPLE INC`). |
| `.../BalForAcct/AggtBal/Unit` | Decimal | Required | **Aggregate Balance / Unit**: Total quantity of units or shares held. |
| `.../BalForAcct/PricDtls/Val` | Decimal | Optional | **Price Details / Value**: Unit price of the security. Carries `Ccy` currency attribute. |
| `.../BalForAcct/PricDtls/Dt` | Date | Optional | **Price Details / Date**: Pricing date (YYYY-MM-DD). |
| `.../BalForAcct/AcctBaseCcyAmts/HldgVal/Amt` | Decimal | Optional | **Account Base Currency Amounts / Holding Value / Amount**: Total position market value (Units $\times$ Price). Carries `Ccy` currency attribute. |

#### Limitations
* **No Cost Basis:** The `semt.002` subset does not carry position cost basis. `cost_basis` is initialized as `None` when parsing this format.

---

## 2. MT535 (SWIFT / ISO 15022 Statement of Holdings)

### Structure
A line-based, tag-qualifier text format. Blocks are opened with `:16R:BLOCKNAME` and closed with `:16S:BLOCKNAME`.

### Sample File Structure
```text
:16R:GENL
:20C::SEME//STMT-2026-07-16-60011234
:23G:NEWM
:98A::STAT//2026-07-16
:97A::SAFE//60011234
:16S:GENL
:16R:FIN
:35B:ISIN US0378331005
APPLE INC
:93B::AGGR//UNIT/22792,
:90B::MRKT//ACTU/USD253,79
:98A::PRIC//2026-07-16
:19A::HOLD//USD5784381,68
:70E::HOLD//COST/USD205,50
:16S:FIN
```

### Tag & Block Specifications

#### A. GENL Block (General metadata - General Information)
* **`:16R:GENL` / `:16S:GENL`**: Start and end boundaries of the **General Information** block.
* **`:20C::SEME//`** *(Sender's Message Reference)*: **Statement Identifier**: Unique sender reference.
* **`:23G:`** *(Function of Message)*: **Message Function** (here `NEWM` for new statement).
* **`:98A::STAT//`** *(Statement Date)*: **Statement Date**: Date at which balances are conformed (`YYYYMMDD` format).
* **`:97A::SAFE//`** *(Safekeeping Account)*: **Safekeeping Account**: Custodian account number.

#### B. FIN Block (Positions section - Financial Instrument Accounts - Repeating)
* **`:16R:FIN` / `:16S:FIN`**: Start and end boundaries of the **Financial Instrument Accounts** block.
* **`:35B:ISIN `** *(Identification of Financial Instrument)*: **Security Identifier**: The first line contains the scheme prefix (e.g. `ISIN US0378331005` or `/XX/CUSIPVALUE`). The next line is the text description of the security.
* **`:93B::AGGR//UNIT/`** *(Aggregate Balance)*: **Aggregate Quantity**: Total share/unit quantity.
* **`:90B::MRKT//ACTU/`** *(Price / Market Price)*: **Security Price**: Per-unit market price. Carries a 3-letter currency code prefix followed by the price.
* **`:98A::PRIC//`** *(Price Date)*: **Price Date**: Pricing date (`YYYYMMDD`).
* **`:19A::HOLD//`** *(Amount / Holding Value)*: **Position Market Value**: Total holding valuation. Carries a currency code prefix followed by the conformed total amount.
* **`:70E::HOLD//COST/`** *(Narrative / Cost Basis)*: **Cost Basis Narrative**: Smuggled cost basis information. We parse the structure `COST/<CURRENCY><AMOUNT>` out of this free-text field.

### Format Conventions
* **Decimal Comma:** All numbers in MT535 use commas as the decimal separator instead of dots. Whole numbers must terminate with a comma (e.g. `22792,` = 22792; `253,79` = 253.79).
* **Continuity Lines:** Fields spanning multiple lines (like `:35B:`) append their remaining lines directly without a leading colon.

---

## 3. camt.053 (ISO 20022 Bank-to-Customer Statement)

### Namespace
`urn:iso:std:iso:20022:tech:xsd:camt.053.001.08`

### One file, many statements
Unlike the two holdings formats (one account per message), camt.053 carries a
repeating `Stmt` block — the custodian's daily cash file (`CUSTGB2L.camt053.xml`)
contains one statement per cash account it services, each with its own account
block, balances, entries, and currency. The sample below shows a single `Stmt`;
the daily file repeats it per account.

### Sample File Structure
```xml
<?xml version='1.0' encoding='utf-8'?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08">
  <BkToCstmrStmt>
    <GrpHdr>
      <MsgId>CAMT-2026-07-16</MsgId>
      <CreDtTm>2026-07-16T00:00:00</CreDtTm>
    </GrpHdr>
    <Stmt>
      <Id>CASH-2026-07-16-60011234</Id>
      <Acct>
        <Id>
          <Othr>
            <Id>60011234</Id>
          </Othr>
        </Id>
        <Ccy>USD</Ccy>
        <Nm>Growth Portfolio</Nm>
        <Svcr>
          <FinInstnId>
            <BICFI>CUSTGB2LXXX</BICFI>
          </FinInstnId>
        </Svcr>
      </Acct>
      <!-- Balances (Opening OPBD + Closing CLBD) -->
      <Bal>
        <Tp>
          <CdOrPrtry>
            <Cd>OPBD</Cd>
          </CdOrPrtry>
        </Tp>
        <Amt Ccy="USD">50000.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <Dt>
          <Dt>2026-07-09</Dt>
        </Dt>
      </Bal>
      <Bal>
        <Tp>
          <CdOrPrtry>
            <Cd>CLBD</Cd>
          </CdOrPrtry>
        </Tp>
        <Amt Ccy="USD">54234.95</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <Dt>
          <Dt>2026-07-16</Dt>
        </Dt>
      </Bal>
      <!-- Cash Entry (Repeated) -->
      <Ntry>
        <NtryRef>TXN-2026-07-16-0001</NtryRef>
        <Amt Ccy="USD">484.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <Sts>
          <Cd>BOOK</Cd>
        </Sts>
        <BookgDt>
          <Dt>2026-07-14</Dt>
        </BookgDt>
        <ValDt>
          <Dt>2026-07-14</Dt>
        </ValDt>
        <BkTxCd>
          <Prtry>
            <Cd>DIVIDEND</Cd>
          </Prtry>
        </BkTxCd>
        <AddtlNtryInf>Dividend Apple Inc</AddtlNtryInf>
      </Ntry>
    </Stmt>
  </BkToCstmrStmt>
</Document>
```

### Tag Dictionary & Semantics

| XML Path | Type | Optionality | Description |
|---|---|---|---|
| `/Document/BkToCstmrStmt` | Element | Required | **Bank to Customer Statement**: Root wrapper containing account transactions and balances. |
| `.../GrpHdr/MsgId` | String | Required | **Group Header / Message Identifier**: Unique ID for the file/transmission run. |
| `.../GrpHdr/CreDtTm` | DateTime | Required | **Group Header / Creation Date Time**: File generation timestamp (YYYY-MM-DDThh:mm:ss). |
| `.../Stmt/Id` | String | Required | **Statement / Identifier**: Unique run ID of this statement instance. |
| `.../Stmt/Acct` | Element | Required | **Statement / Account**: Account metadata. |
| `.../Acct/Id/Othr/Id` | String | Required | **Account / Identifier / Other / Identifier**: Cash account identifier (number). |
| `.../Acct/Ccy` | String | Required | **Account / Currency**: Currency code of the cash account. |
| `.../Acct/Nm` | String | Optional | **Account / Name**: Display name of the account owner. |
| `.../Acct/Svcr/FinInstnId/BICFI` | String | Optional | **Account / Servicer / Financial Institution Identification / Business Identifier Code Financial Institution**: BIC of the servicing bank. |
| `.../Stmt/Bal` | Element | Repeating | **Statement / Balance**: Account balance records. Must include opening and closing balance blocks. |
| `.../Bal/Tp/CdOrPrtry/Cd` | String | Required | **Balance / Type / Code or Proprietary / Code**: Balance type code: `OPBD` (**Opening Booked Balance**) or `CLBD` (**Closing Booked Balance**). |
| `.../Bal/Amt` | Decimal | Required | **Balance / Amount**: Balance amount. Carries `Ccy` currency attribute. |
| `.../Bal/CdtDbtInd` | String | Required | **Balance / Credit Debit Indicator**: Balance direction: `CRDT` (**Credit** / positive cash) or `DBIT` (**Debit** / overdrawn cash). |
| `.../Bal/Dt/Dt` | Date | Required | **Balance / Date / Date**: Balance statement date. |
| `.../Stmt/Ntry` | Element | Repeating | **Statement / Entry**: Individual transaction entry representing a cash ledger movement. |
| `.../Ntry/NtryRef` | String | Required | **Entry / Entry Reference**: Unique transaction ID. |
| `.../Ntry/Amt` | Decimal | Required | **Entry / Amount**: Transaction value. Carries `Ccy` currency attribute. |
| `.../Ntry/CdtDbtInd` | String | Required | **Entry / Credit Debit Indicator**: Cash flow direction: `DBIT` (**Debit** / cash leaving) or `CRDT` (**Credit** / cash entering). |
| `.../Ntry/Sts/Cd` | String | Required | **Entry / Status / Code**: Posting status. Typically `BOOK` (**Booked**). |
| `.../Ntry/BookgDt/Dt` | Date | Required | **Entry / Booking Date / Date**: Booking date (when recorded; mapped to conformed `trade_date`). |
| `.../Ntry/ValDt/Dt` | Date | Required | **Entry / Value Date / Date**: Value/settlement date (when interest/cash active; mapped to `settlement_date`). |
| `.../Ntry/BkTxCd/Prtry/Cd` | String | Required | **Entry / Bank Transaction Code / Proprietary / Code**: Bank's proprietary transaction type (e.g. `BUY`, `SELL`, `DIVIDEND`, `INTEREST`, `FEE`, `TRANSFER_IN`, `TRANSFER_OUT`). |
| `.../Ntry/AddtlNtryInf` | String | Optional | **Entry / Additional Entry Information**: Description/memo detailing the cash movement. |
