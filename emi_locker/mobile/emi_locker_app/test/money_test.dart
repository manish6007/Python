import 'package:emi_locker_app/core/money.dart';
import 'package:emi_locker_app/core/request_id.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('Money', () {
    test('formats whole rupees without decimals', () {
      expect(Money.format(200000), '₹2,000');
      expect(Money.format(2200000), '₹22,000');
      expect(Money.format(0), '₹0');
    });

    test('shows paise only when there are any', () {
      expect(Money.format(200050), '₹2,000.50');
    });

    test('parses what a retailer types into paise', () {
      expect(Money.toPaise('30000'), 3000000);
      expect(Money.toPaise('30,000'), 3000000);
      expect(Money.toPaise(' 2500.50 '), 250050);
      expect(Money.toPaise('₹1000'), 100000);
    });

    test('rejects junk instead of guessing', () {
      expect(Money.toPaise(''), isNull);
      expect(Money.toPaise('abc'), isNull);
      expect(Money.toPaise('-100'), isNull);
    });

    test('round trips without drifting', () {
      for (final rupees in ['30000', '22000', '1999.99', '0.01', '12345.67']) {
        final paise = Money.toPaise(rupees)!;
        expect(Money.toPaise(Money.toRupeeString(paise)), paise,
            reason: 'drifted for $rupees');
      }
    });
  });

  group('IMEI validation', () {
    test('accepts valid IMEIs', () {
      expect(isValidImei('490154203237518'), isTrue);
      expect(isValidImei('356938035643809'), isTrue);
    });

    test('rejects a wrong check digit, wrong length and non-digits', () {
      expect(isValidImei('490154203237519'), isFalse);
      expect(isValidImei('49015420323751'), isFalse);
      expect(isValidImei('49015420323751A'), isFalse);
      expect(isValidImei(''), isFalse);
    });
  });

  group('request ids', () {
    test('are unique per call', () {
      final ids = List.generate(200, (_) => newRequestId('fin'));
      expect(ids.toSet().length, 200);
      expect(ids.first.startsWith('fin-'), isTrue);
    });
  });

  group('date formatting', () {
    test('renders ISO dates readably and tolerates junk', () {
      expect(formatDate('2026-10-10'), '10 Oct 2026');
      expect(formatDate(null), '-');
      expect(formatDate(''), '-');
      expect(formatDate('not-a-date'), 'not-a-date');
    });
  });
}
