import 'package:flutter/material.dart';

import '../../core/money.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';
import '../../main.dart';
import 'pay_screen.dart';

/// One finance account: terms, progress and the full EMI schedule.
///
/// Shared by both audiences - the retailer opens the same screen from a
/// customer's profile. The backend decides what each role may see, so the
/// screen does not need two versions.
class FinanceDetailScreen extends StatelessWidget {
  const FinanceDetailScreen({
    super.key,
    required this.financeId,
    this.allowPay = true,
  });

  final String financeId;
  final bool allowPay;

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Finance details')),
      body: AsyncView<List<dynamic>>(
        load: () => Future.wait([
          session.api.get('/finance/$financeId'),
          session.api.get('/finance/$financeId/emi-schedule'),
        ]),
        builder: (context, data, reload) {
          final detail = Map<String, dynamic>.from(data[0] as Map);
          final schedule = List<Map<String, dynamic>>.from(
            ((data[1] as Map)['schedule'] as List)
                .map((e) => Map<String, dynamic>.from(e as Map)),
          );
          final nextDue = detail['next_due'] as Map?;
          final canPay = allowPay &&
              session.isCustomer &&
              nextDue != null &&
              detail['status'] != 'COMPLETED';

          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              _SummaryCard(detail: detail),
              const SizedBox(height: 16),
              if (canPay)
                FilledButton.icon(
                  onPressed: () async {
                    final paid = await Navigator.of(context).push<bool>(
                      MaterialPageRoute(
                        builder: (_) => PayScreen(
                          financeId: financeId,
                          emiId: nextDue['id'].toString(),
                          seq: nextDue['seq'] as int,
                          amountPaise: nextDue['amount_paise'] as int,
                          dueDate: nextDue['due_date'].toString(),
                        ),
                      ),
                    );
                    if (paid == true) await reload();
                  },
                  icon: const Icon(Icons.payment),
                  label: Text('Pay EMI ${nextDue['seq']} '
                      '• ${Money.format(nextDue['amount_paise'] as int)}'),
                ),
              if (canPay) const SizedBox(height: 24),
              Text('Repayment schedule',
                  style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              Card(
                child: Column(
                  children: [
                    for (var i = 0; i < schedule.length; i++) ...[
                      if (i > 0) const Divider(height: 1),
                      _ScheduleRow(row: schedule[i]),
                    ],
                  ],
                ),
              ),
              const SizedBox(height: 32),
            ],
          );
        },
      ),
    );
  }
}

class _SummaryCard extends StatelessWidget {
  const _SummaryCard({required this.detail});

  final Map<String, dynamic> detail;

  @override
  Widget build(BuildContext context) {
    final device = detail['device'] as Map?;
    final customer = detail['customer'] as Map?;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    device?['model']?.toString() ?? 'Financed device',
                    style: Theme.of(context)
                        .textTheme
                        .titleMedium
                        ?.copyWith(fontWeight: FontWeight.w600),
                  ),
                ),
                StatusChip(status: detail['status'].toString()),
              ],
            ),
            const SizedBox(height: 4),
            Text(detail['finance_id'].toString(),
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    )),
            const Divider(height: 28),
            if (customer != null)
              LabelledRow('Customer', customer['name'].toString()),
            LabelledRow('IMEI', device?['imei']?.toString() ?? '-'),
            LabelledRow('Device status',
                prettyStatus(device?['status']?.toString() ?? '-')),
            const Divider(height: 24),
            LabelledRow('Product price', Money.format(detail['product_price'] as int)),
            LabelledRow('Down payment', Money.format(detail['down_payment'] as int)),
            LabelledRow('Financed amount', Money.format(detail['principal'] as int)),
            LabelledRow('Monthly EMI', Money.format(detail['emi_amount'] as int)),
            LabelledRow('Tenure', '${detail['tenure_months']} months'),
            LabelledRow('Started', formatDate(detail['start_date']?.toString())),
            const Divider(height: 24),
            LabelledRow('Paid so far', Money.format(detail['paid_paise'] as int)),
            LabelledRow(
              'Outstanding',
              Money.format(detail['outstanding_paise'] as int),
              valueStyle: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                    color: (detail['outstanding_paise'] as int) == 0
                        ? statusColor(context, 'PAID')
                        : null,
                  ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ScheduleRow extends StatelessWidget {
  const _ScheduleRow({required this.row});

  final Map<String, dynamic> row;

  @override
  Widget build(BuildContext context) {
    final status = row['status'].toString();
    final paid = status == 'PAID';
    return ListTile(
      leading: CircleAvatar(
        radius: 16,
        backgroundColor: statusColor(context, status).withValues(alpha: 0.14),
        child: paid
            ? Icon(Icons.check, size: 16, color: statusColor(context, status))
            : Text('${row['seq']}',
                style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: statusColor(context, status))),
      ),
      title: Text(Money.format(row['amount_paise'] as int),
          style: const TextStyle(fontWeight: FontWeight.w600)),
      subtitle: Text(paid
          ? 'Paid ${formatDate(row['paid_at']?.toString().split('T').first)}'
          : 'Due ${formatDate(row['due_date']?.toString())}'),
      trailing: StatusChip(status: status, dense: true),
    );
  }
}
