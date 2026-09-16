import 'package:intl/intl.dart';

/// All money crosses the API as integer paise. Rupees only exist for display
/// and for what the user types, and they are converted here and nowhere else.
///
/// Doing this in one place is the point: a stray `double` in the money path is
/// how ledgers end up a paisa short.
class Money {
  static final NumberFormat _inr = NumberFormat.currency(
    locale: 'en_IN',
    symbol: '₹',
    decimalDigits: 0,
  );

  static final NumberFormat _inrPaise = NumberFormat.currency(
    locale: 'en_IN',
    symbol: '₹',
    decimalDigits: 2,
  );

  /// `250000` -> `₹2,500`, or `₹2,500.50` when there are paise to show.
  static String format(int paise) {
    if (paise % 100 == 0) {
      return _inr.format(paise ~/ 100);
    }
    return _inrPaise.format(paise / 100);
  }

  /// Rupees the user typed -> paise. Returns null when it is not a number.
  static int? toPaise(String rupees) {
    final cleaned = rupees.replaceAll(',', '').replaceAll('₹', '').trim();
    if (cleaned.isEmpty) return null;
    final value = double.tryParse(cleaned);
    if (value == null || value < 0) return null;
    return (value * 100).round();
  }

  static String toRupeeString(int paise) => (paise / 100).toStringAsFixed(
        paise % 100 == 0 ? 0 : 2,
      );
}

/// Dates arrive as `YYYY-MM-DD`; show them the way an Indian retailer reads them.
String formatDate(String? iso) {
  if (iso == null || iso.isEmpty) return '-';
  final date = DateTime.tryParse(iso);
  if (date == null) return iso;
  return DateFormat('d MMM yyyy').format(date);
}

String formatDateTime(String? iso) {
  if (iso == null || iso.isEmpty) return '-';
  final date = DateTime.tryParse(iso);
  if (date == null) return iso;
  return DateFormat('d MMM yyyy, h:mm a').format(date.toLocal());
}
