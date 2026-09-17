import 'package:flutter/material.dart';

import '../../core/adaptive.dart';
import '../../core/money.dart';
import '../../core/widgets.dart';
import '../../main.dart';

/// Every verified payment and every failure, newest first.
class AdminPayments extends StatelessWidget {
  const AdminPayments({super.key});

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        PageBody(
          child: SizedBox(
            height: MediaQuery.sizeOf(context).height * 0.78,
            child: AsyncView<Map<String, dynamic>>(
              load: () async => Map<String, dynamic>.from(
                  await session.api.get('/admin/payments') as Map),
              builder: (context, data, reload) {
                final payments = List<Map<String, dynamic>>.from(
                    (data['payments'] as List)
                        .map((e) => Map<String, dynamic>.from(e as Map)));
                final collected = payments
                    .where((p) => p['status'] == 'SUCCESS')
                    .fold<int>(0, (sum, p) => sum + (p['amount_paise'] as int));
                return ListView(
                  children: [
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(18),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('Collected in these ${payments.length} records',
                                style: Theme.of(context)
                                    .textTheme
                                    .labelLarge
                                    ?.copyWith(
                                      color: Theme.of(context)
                                          .colorScheme
                                          .onSurfaceVariant,
                                    )),
                            const SizedBox(height: 6),
                            MoneyText(collected, emphasise: true),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),
                    RecordTable(
                      emptyMessage: 'No payments recorded yet',
                      columns: const [
                        'Payment',
                        'Customer',
                        'Retailer',
                        'EMI',
                        'Amount',
                        'Method',
                        'Status',
                        'Receipt',
                        'Gateway ref',
                        'When'
                      ],
                      rows: [
                        for (final payment in payments)
                          [
                            Text(payment['payment_id'].toString()),
                            Text(payment['customer_name'].toString()),
                            Text(payment['retailer_name'].toString()),
                            Text(payment['emi_seq']?.toString() ?? '-'),
                            Text(Money.format(payment['amount_paise'] as int)),
                            Text(payment['method'].toString()),
                            StatusChip(
                                status: payment['status'] == 'SUCCESS'
                                    ? 'PAID'
                                    : payment['status'].toString(),
                                dense: true),
                            Text(payment['receipt_number']?.toString() ?? '-'),
                            Text(payment['gateway_txn_id']?.toString() ?? '-'),
                            Text(formatDateTime(payment['updated_at']?.toString())),
                          ],
                      ],
                    ),
                  ],
                );
              },
            ),
          ),
        ),
      ],
    );
  }
}
