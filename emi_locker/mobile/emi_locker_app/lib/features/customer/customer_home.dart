import 'package:flutter/material.dart';

import '../../core/money.dart';
import '../../core/widgets.dart';
import '../../main.dart';
import 'finance_detail.dart';

class CustomerHome extends StatelessWidget {
  const CustomerHome({super.key});

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    return AsyncView<Map<String, dynamic>>(
      load: () async =>
          Map<String, dynamic>.from(await session.api.get('/me/finances') as Map),
      builder: (context, data, reload) {
        final finances = List<Map<String, dynamic>>.from(
            (data['finances'] as List).map((e) => Map<String, dynamic>.from(e as Map)));
        if (finances.isEmpty) {
          return ListView(
            children: const [
              SizedBox(height: 120),
              EmptyState(
                icon: Icons.phone_android,
                title: 'No EMI plan yet',
                subtitle:
                    'When your retailer sets up a finance for your device, it '
                    'will appear here.',
              ),
            ],
          );
        }
        return ListView.separated(
          padding: const EdgeInsets.all(16),
          itemCount: finances.length,
          separatorBuilder: (_, __) => const SizedBox(height: 16),
          itemBuilder: (context, index) =>
              _FinanceCard(finance: finances[index], onChanged: reload),
        );
      },
    );
  }
}

class _FinanceCard extends StatelessWidget {
  const _FinanceCard({required this.finance, required this.onChanged});

  final Map<String, dynamic> finance;
  final Future<void> Function() onChanged;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final nextDue = finance['next_due'] as Map?;
    final outstanding = finance['outstanding_paise'] as int;
    final principal = finance['principal'] as int;
    final paidFraction =
        principal == 0 ? 1.0 : (principal - outstanding) / principal;

    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: () async {
          await Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => FinanceDetailScreen(
              financeId: finance['finance_id'].toString(),
            ),
          ));
          await onChanged();
        },
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(Icons.smartphone, color: scheme.primary),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          finance['model']?.toString() ?? 'Financed device',
                          style: Theme.of(context)
                              .textTheme
                              .titleMedium
                              ?.copyWith(fontWeight: FontWeight.w600),
                        ),
                        Text(
                          'IMEI ${finance['imei'] ?? '-'}',
                          style: Theme.of(context)
                              .textTheme
                              .bodySmall
                              ?.copyWith(color: scheme.onSurfaceVariant),
                        ),
                      ],
                    ),
                  ),
                  StatusChip(status: finance['status'].toString()),
                ],
              ),
              const SizedBox(height: 18),
              Text('Outstanding',
                  style: Theme.of(context)
                      .textTheme
                      .labelMedium
                      ?.copyWith(color: scheme.onSurfaceVariant)),
              const SizedBox(height: 2),
              MoneyText(outstanding, emphasise: true),
              const SizedBox(height: 14),
              ClipRRect(
                borderRadius: BorderRadius.circular(8),
                child: LinearProgressIndicator(
                  value: paidFraction.clamp(0.0, 1.0),
                  minHeight: 8,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                '${finance['paid_count']} of ${finance['tenure_months']} instalments paid',
                style: Theme.of(context)
                    .textTheme
                    .bodySmall
                    ?.copyWith(color: scheme.onSurfaceVariant),
              ),
              if (nextDue != null) ...[
                const Divider(height: 28),
                Row(
                  children: [
                    Icon(Icons.event, size: 18, color: scheme.onSurfaceVariant),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        'Next: EMI ${nextDue['seq']} due '
                        '${formatDate(nextDue['due_date']?.toString())}',
                        style: Theme.of(context).textTheme.bodyMedium,
                      ),
                    ),
                    StatusChip(status: nextDue['status'].toString(), dense: true),
                  ],
                ),
              ],
              if (finance['device_status'] == 'RESTRICTED') ...[
                const SizedBox(height: 12),
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: scheme.errorContainer,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Row(
                    children: [
                      Icon(Icons.lock, size: 18, color: scheme.onErrorContainer),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          'This device is restricted because an instalment is '
                          'overdue. Clearing the arrears restores it.',
                          style: TextStyle(
                              fontSize: 12, color: scheme.onErrorContainer),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
