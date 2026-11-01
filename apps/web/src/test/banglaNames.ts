/**
 * F-115: BD-convention fixture names for tests that render people.
 *
 * Real rosters carry long, matra-heavy and compound forms; Latin placeholders
 * like "A B" do not exercise the width, wrapping or initial-extraction paths
 * the way these do. The API-side mailer/CSV/PDF fixtures live in
 * apps/api/tests/conftest.py.
 */
export const BANGLA_NAME_FIXTURES = [
  "মোছাম্মৎ নূরজাহান বেগম",
  "শ্রাবন্তী রায়",
  "মুহাম্মদ আবদুল করিম উদ্দিন",
  "নাফিসা তাসনিম",
  "রিফাত হোসেন",
  "তানজিলা আক্তার",
  "সাইয়েদ মোহাম্মদ ইসহাক",
  "জান্নাতুল ফেরদৌস",
] as const;
