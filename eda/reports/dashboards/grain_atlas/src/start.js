/* ================================================================ start */
initDecisions();
const start=resolve(location.hash)||resolve(store.get("grain.route"))||"mission";
go(start);
