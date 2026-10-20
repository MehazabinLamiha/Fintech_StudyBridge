// Dev only: loaded by app.js when the URL has ?data=demo|worst|empty|one. Fills the sandbox through the same actions
// the screens use (never by editing markup), so Bank, Messages and Bills can be checked with realistic worst-case data.
// Limits come from the code: payee name 60 (payments.add_payee), bill purpose 80 (invoicelab._clean), amount
// 1,000,000 (invoicelab.make), each sample message once (inbox.send), bank limit USD 100-1,000, family limit CNY 5,000.
(() => {
  const MODES = [["demo", "Demo data"], ["worst", "Worst case"], ["empty", "Empty"], ["one", "One"]];
  const mode = new URLSearchParams(location.search).get("data");

  const LANDLORD = "Shenzhen Nanshan Xili International Student Apartments Ltd.";   // 59 characters
  const SHOP = "Huaqiangbei Electronics Wholesale Market, Stall 3F-B127";
  const payeeId = (name) => state.book.payees.find((p) => p.name === name).id;
  const pay = async (msg) => {
    const r = await act("student", "chat", { message: msg });
    if (r.pending_action) await act("student", "confirm", { id: r.pending_action.id });
    return r;
  };

  async function worst() {
    await act("family", "add_payee", { name: LANDLORD, type: "landlord", account: "6217003320001234567", confirmed: true });
    await act("family", "add_payee", { name: SHOP, type: "merchant", account: "6228480402564890018", confirmed: true });
    await act("family", "add_payee", { name: "Jo", type: "merchant", account: "62170033", confirmed: true });
    await act("operator", "advance_clock", { hours: 49 });                 // past the 48-hour new-payee wait
    const bill = (payee, kind, amount, purpose, extra = { account_mode: "saved" }) =>
      act("student", "add_bill", { payee_id: payeeId(payee), kind, amount, purpose, ...extra });
    await bill(LANDLORD, "bill", "4999.99", "12-month lease: deposit, first month's rent and utilities, Building 7, Room 1204");
    await bill(SHOP, "quote", "1000000", "Bulk order: 24 refurbished ThinkPad T14 Gen 3, 32 GB, 1 TB, with carry bags");
    await bill("Jo", "quote", "0.01", "");
    await bill(SHOP, "quote", "2999", "INV#HQB-2026-10-000123456789-REPRINT-COPY2", { account_number: "6228480402564890019" });
    for (const t of ["uni_tuition", "uni_fee", "landlord_rent", "shop_quote", "fake_uni", "fake_uni"]) {   // the repeat is refused
      await act("operator", "send_message", { template: t });
    }
    for (const id of ["BILL-0001", "BILL-0002", "Q-TM-0042"]) {             // long payee, CNY 1,000,000, a plain quote
      const r = await act("student", "chat", { message: `request an allowance for ${id}` });
      if (r.request_id) await act("family", "decide", { request_id: r.request_id, approve: true });
    }
    await pay("pay BILL-0001");                                              // long payee through the card
    await pay("pay 38 CNY at the canteen");
    await act("family", "set_limit", { cny: 5000 });
    await act("bank", "set_bank_limit", { usd: 100 });                      // spending already past the new limit
  }

  async function one() {
    await act("operator", "send_message", { template: "fake_uni" });
    await act("student", "chat", { message: "request an allowance for Q-TM-0042" });
    await pay("pay 38 CNY at the canteen");
  }

  async function run() {
    await act("operator", "reset");
    if (mode === "worst") await worst();
    if (mode === "one") await one();
    toast(`Dev data: ${mode}`);
  }

  // The switch: bottom centre, plain on purpose (it is not part of the design under test).
  const bar = document.createElement("div");
  Object.assign(bar.style, { position: "fixed", left: "50%", bottom: "12px", transform: "translateX(-50%)", zIndex: 60,
    display: "flex", gap: "2px", padding: "3px", borderRadius: "999px", background: "#e5e7eb",
    font: "12px system-ui, sans-serif", boxShadow: "0 1px 4px rgba(0,0,0,.15)" });
  for (const [id, label] of MODES) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    Object.assign(b.style, { padding: "5px 12px", borderRadius: "999px", color: "#111",
      background: id === mode ? "#fff" : "transparent", fontWeight: id === mode ? "600" : "400" });
    b.onclick = () => { location.search = `?data=${id}`; };
    bar.append(b);
  }
  document.body.append(bar);
  if (MODES.some(([id]) => id === mode)) run();
})();
