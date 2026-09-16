import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/money.dart';
import '../../core/widgets.dart';
import '../../main.dart';

class RetailerHome extends StatelessWidget {
  const RetailerHome({super.key});

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    return AsyncView<Map<String, dynamic>>(
      load: () async => Map<String, dynamic>.from(
          await session.api.get('/retailer/dashboard') as Map),
      builder: (context, data, reload) {
        final wallet = Map<String, dynamic>.from(data['wallet'] as Map);
        final available = wallet['available'] as int;
        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            _ActivationBalance(wallet: wallet),
            const SizedBox(height: 16),
            GridView.count(
              crossAxisCount: 2,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              mainAxisSpacing: 12,
              crossAxisSpacing: 12,
              childAspectRatio: 1.35,
              children: [
                StatTile(
                  label: 'Customers',
                  value: '${data['customers']}',
                  icon: Icons.people_outline,
                ),
                StatTile(
                  label: 'Active finance',
                  value: '${data['active_finance']}',
                  icon: Icons.check_circle_outline,
                ),
                StatTile(
                  label: 'Overdue accounts',
                  value: '${data['overdue_finance']}',
                  icon: Icons.warning_amber_outlined,
                  tone: (data['overdue_finance'] as int) > 0
                      ? Theme.of(context).colorScheme.error
                      : null,
                ),
                StatTile(
                  label: 'Completed',
                  value: '${data['completed_finance']}',
                  icon: Icons.verified_outlined,
                ),
                StatTile(
                  label: 'Outstanding book',
                  value: Money.format(data['outstanding_paise'] as int),
                  icon: Icons.account_balance_wallet_outlined,
                ),
                StatTile(
                  label: 'Collected today',
                  value: Money.format(data['collected_today_paise'] as int),
                  icon: Icons.today_outlined,
                ),
              ],
            ),
            const SizedBox(height: 24),
            Text('Testing tools',
                style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 8),
            Card(
              child: ListTile(
                leading: const Icon(Icons.update),
                title: const Text('Run the daily status sweep'),
                subtitle: const Text(
                    'Moves instalments to due / grace / overdue without waiting '
                    'for the nightly job. Local testing only.'),
                onTap: () async {
                  try {
                    final out = await session.api
                        .post('/retailer/run-daily-sweep') as Map;
                    final moved = Map<String, dynamic>.from(out['moved'] as Map);
                    if (!context.mounted) return;
                    showOk(context,
                        'Sweep done — due: ${moved['DUE']}, grace: ${moved['GRACE_PERIOD']}, overdue: ${moved['OVERDUE']}');
                    await reload();
                  } on ApiException catch (error) {
                    if (context.mounted) showError(context, error);
                  }
                },
              ),
            ),
            if (available <= 5) ...[
              const SizedBox(height: 16),
              Card(
                color: Theme.of(context).colorScheme.errorContainer,
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Text(
                    available == 0
                        ? 'You have no activations left. New finance cannot be '
                            'created until your distributor allocates more.'
                        : 'Only $available activations left. Ask your '
                            'distributor for more before you run out.',
                    style: TextStyle(
                        color: Theme.of(context).colorScheme.onErrorContainer),
                  ),
                ),
              ),
            ],
            const SizedBox(height: 32),
          ],
        );
      },
    );
  }
}

/// The retailer's licence balance: how many more devices they may activate.
class _ActivationBalance extends StatelessWidget {
  const _ActivationBalance({required this.wallet});

  final Map<String, dynamic> wallet;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final total = wallet['total'] as int;
    final used = wallet['used'] as int;
    final available = wallet['available'] as int;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.key_outlined, color: scheme.primary),
                const SizedBox(width: 8),
                Expanded(
                  child: Text('Activation balance',
                      style: Theme.of(context).textTheme.titleMedium),
                ),
              ],
            ),
            const SizedBox(height: 14),
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text('$available',
                    style: Theme.of(context).textTheme.displaySmall?.copyWith(
                          fontWeight: FontWeight.w700,
                          color: available == 0 ? scheme.error : null,
                        )),
                const SizedBox(width: 8),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: Text('of $total available',
                        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                              color: scheme.onSurfaceVariant,
                            )),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: LinearProgressIndicator(
                value: total == 0 ? 0 : used / total,
                minHeight: 8,
              ),
            ),
            const SizedBox(height: 8),
            Text('$used used • each new finance uses one',
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: scheme.onSurfaceVariant,
                    )),
          ],
        ),
      ),
    );
  }
}
