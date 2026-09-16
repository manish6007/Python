import 'package:flutter/material.dart';

import '../../core/money.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';
import '../../main.dart';
import 'receipt_screen.dart';

class CustomerPayments extends StatelessWidget {
  const CustomerPayments({super.key});

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    return AsyncView<Map<String, dynamic>>(
      load: () async =>
          Map<String, dynamic>.from(await session.api.get('/me/payments') as Map),
      builder: (context, data, reload) {
        final payments = List<Map<String, dynamic>>.from(
            (data['payments'] as List).map((e) => Map<String, dynamic>.from(e as Map)));
        if (payments.isEmpty) {
          return ListView(
            children: const [
              SizedBox(height: 120),
              EmptyState(
                icon: Icons.receipt_long_outlined,
                title: 'No payments yet',
                subtitle: 'Your payment history and receipts will appear here.',
              ),
            ],
          );
        }
        return ListView.separated(
          padding: const EdgeInsets.all(16),
          itemCount: payments.length,
          separatorBuilder: (_, __) => const SizedBox(height: 10),
          itemBuilder: (context, index) {
            final payment = payments[index];
            final success = payment['status'] == 'SUCCESS';
            return Card(
              child: ListTile(
                leading: CircleAvatar(
                  backgroundColor:
                      statusColor(context, success ? 'PAID' : 'OVERDUE')
                          .withValues(alpha: 0.14),
                  child: Icon(
                    success ? Icons.check : Icons.close,
                    color: statusColor(context, success ? 'PAID' : 'OVERDUE'),
                  ),
                ),
                title: Text(Money.format(payment['amount_paise'] as int),
                    style: const TextStyle(fontWeight: FontWeight.w600)),
                subtitle: Text(
                  '${payment['emi_seq'] != null ? 'EMI ${payment['emi_seq']} • ' : ''}'
                  '${payment['method'] == 'ONLINE' ? 'Online' : 'Cash'} • '
                  '${formatDateTime(payment['updated_at']?.toString())}',
                ),
                trailing: success && payment['receipt_number'] != null
                    ? const Icon(Icons.chevron_right)
                    : StatusChip(status: payment['status'].toString(), dense: true),
                onTap: success && payment['receipt_number'] != null
                    ? () => Navigator.of(context).push(MaterialPageRoute(
                          builder: (_) => ReceiptScreen(
                            paymentId: payment['payment_id'].toString(),
                          ),
                        ))
                    : null,
              ),
            );
          },
        );
      },
    );
  }
}
