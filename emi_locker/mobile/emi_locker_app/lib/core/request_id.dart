import 'dart:math';

/// A key that makes a retry safe.
///
/// Generated once when the user starts an action and reused for every retry of
/// that same action, so a lost response or an impatient second tap cannot
/// create two finances or take two payments. Generating it per HTTP call would
/// defeat the whole point.
String newRequestId([String prefix = 'req']) {
  final random = Random.secure();
  final suffix =
      List.generate(8, (_) => random.nextInt(16).toRadixString(16)).join();
  return '$prefix-${DateTime.now().millisecondsSinceEpoch}-$suffix';
}

/// Luhn check on a 15-digit IMEI, so the retailer is told about a typo before
/// a round trip. The backend checks it again - this is convenience, not trust.
bool isValidImei(String imei) {
  final digits = imei.trim();
  if (digits.length != 15 || !RegExp(r'^\d{15}$').hasMatch(digits)) return false;
  var sum = 0;
  for (var i = 0; i < 15; i++) {
    var digit = int.parse(digits[14 - i]);
    if (i.isOdd) {
      digit *= 2;
      if (digit > 9) digit -= 9;
    }
    sum += digit;
  }
  return sum % 10 == 0;
}
