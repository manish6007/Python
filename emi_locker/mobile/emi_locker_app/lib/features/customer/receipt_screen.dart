import 'package:flutter/material.dart';

import '../../core/money.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';
import '../../main.dart';

class ReceiptScreen extends StatelessWidget {
  const ReceiptScreen({super.key, required this.paymentId});

  final String paymentId;

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Receipt')),
      body: AsyncView<Map<String, dynamic>>(
        load: () async => Map<String, dynamic>.from(
            await session.api.get('/receipts/$paymentId') as Map),
        builder: (context, receipt, reload) => ListView(
          padding: const EdgeInsets.all(20),
          children: [
            const SizedBox(height: 12),
            Icon(Icons.check_circle,
                size: 64, color: statusColor(context, 'PAID')),
            const SizedBox(height: 12),
            Text('Payment received',
                textAlign: TextAlign.center,
                style: Theme.of(context)
                    .textTheme
                    .titleLarge
                    ?.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 6),
            Text(
              Money.format(receipt['amount_paise'] as int),
              textAlign: TextAlign.center,
              style: Theme.of(context)
                  .textTheme
                  .headlineMedium
                  ?.copyWith(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 28),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(18),
                child: Column(
                  children: [
                    LabelledRow('Receipt no.', receipt['receipt_number'].toString()),
                    LabelledRow('Date', formatDateTime(receipt['issued_at']?.toString())),
                    LabelledRow('Instalment', 'EMI ${receipt['emi_seq'] ?? '-'}'),
                    LabelledRow('Method',
                        receipt['method'] == 'ONLINE' ? 'Online' : 'Cash'),
                    const Divider(height: 24),
                    LabelledRow('Customer', receipt['customer_name'].toString()),
                    LabelledRow('Mobile', receipt['customer_mobile'].toString()),
                    LabelledRow('Collected by', receipt['retailer_name'].toString()),
                    LabelledRow('Finance', receipt['finance_id'].toString()),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 24),
            Text(
              'Keep this receipt number for your records.',
              textAlign: TextAlign.center,
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(color: scheme.onSurfaceVariant),
            ),
            const SizedBox(height: 24),
            FilledButton(
              onPressed: () => Navigator.of(context).popUntil((r) => r.isFirst),
              child: const Text('Done'),
            ),
          ],
        ),
      ),
    );
  }
}
