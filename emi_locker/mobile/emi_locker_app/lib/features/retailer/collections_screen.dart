import 'package:flutter/material.dart';

import '../../core/money.dart';
import '../../core/theme.dart';
import '../../core/widgets.dart';
import '../../main.dart';
import 'collect_screen.dart';

/// What this retailer should be chasing today, worst first.
class CollectionsScreen extends StatelessWidget {
  const CollectionsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    return AsyncView<Map<String, dynamic>>(
      load: () async => Map<String, dynamic>.from(
          await session.api.get('/retailer/collections/pending') as Map),
      builder: (context, data, reload) {
        final pending = List<Map<String, dynamic>>.from(
            (data['pending'] as List).map((e) => Map<String, dynamic>.from(e as Map)));
        if (pending.isEmpty) {
          return ListView(
            children: const [
              SizedBox(height: 100),
              EmptyState(
                icon: Icons.task_alt,
                title: 'Nothing due',
                subtitle:
                    'No instalment is due, in grace or overdue right now.\n\n'
                    'Pull down to refresh, or run the daily sweep from the '
                    'dashboard to advance instalment states while testing.',
              ),
            ],
          );
        }
        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Card(
              color: Theme.of(context).colorScheme.primaryContainer,
              child: Padding(
                padding: const EdgeInsets.all(18),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('To collect',
                        style: Theme.of(context).textTheme.labelLarge?.copyWith(
                              color: Theme.of(context)
                                  .colorScheme
                                  .onPrimaryContainer,
                            )),
                    const SizedBox(height: 4),
                    Text(
                      Money.format(data['total_paise'] as int),
                      style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                            fontWeight: FontWeight.w700,
                            color:
                                Theme.of(context).colorScheme.onPrimaryContainer,
                          ),
                    ),
                    Text(
                      '${pending.length} instalment'
                      '${pending.length == 1 ? '' : 's'} across your book',
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.onPrimaryContainer,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 16),
            for (final item in pending) ...[
              Card(
                child: ListTile(
                  leading: CircleAvatar(
                    backgroundColor:
                        statusColor(context, item['status'].toString())
                            .withValues(alpha: 0.14),
                    child: Text(
                      '${item['seq']}',
                      style: TextStyle(
                        fontWeight: FontWeight.w700,
                        color: statusColor(context, item['status'].toString()),
                      ),
                    ),
                  ),
                  title: Text(item['customer_name'].toString(),
                      style: const TextStyle(fontWeight: FontWeight.w600)),
                  subtitle: Text(
                    '${Money.format(item['amount_paise'] as int)} • due '
                    '${formatDate(item['due_date']?.toString())}'
                    '${(item['days_past_due'] as int) > 0 ? ' • ${item['days_past_due']}d late' : ''}',
                  ),
                  trailing: StatusChip(status: item['status'].toString(), dense: true),
                  onTap: () async {
                    final collected = await Navigator.of(context).push<bool>(
                      MaterialPageRoute(
                        builder: (_) => CollectScreen(
                          financeId: item['finance_id'].toString(),
                          emiId: item['emi_id'].toString(),
                          seq: item['seq'] as int,
                          amountPaise: item['amount_paise'] as int,
                          customerName: item['customer_name'].toString(),
                          mobile: item['mobile'].toString(),
                        ),
                      ),
                    );
                    if (collected == true) await reload();
                  },
                ),
              ),
              const SizedBox(height: 10),
            ],
            const SizedBox(height: 24),
          ],
        );
      },
    );
  }
}
