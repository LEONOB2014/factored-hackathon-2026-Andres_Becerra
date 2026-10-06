export function formatMoney(n: number, currency: string) {
  return `${currency} ${new Intl.NumberFormat("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n)}`;
}
export function formatNum(n: number, digits = 0) {
  return new Intl.NumberFormat("es-AR", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n);
}
