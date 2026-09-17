import 'package:flutter/material.dart';

import '../../core/widgets.dart';
import '../../main.dart';

class DistributorHome extends StatelessWidget {
  const DistributorHome({super.key});

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    return AsyncView<Map<String, dynamic>>(
      load: () async => Map<String, dynamic>.from(
          await session.api.get('/distributor/dashboard') as Map),
      builder: (context, data, reload) {
        final wallet = Map<String, dynamic>.from(data['wallet'] as Map);
        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            _StockCard(
              wallet: wallet,
              allocated: data['allocated_to_retailers'] as int,
              usedDownstream: data['activations_used_downstream'] as int,
            ),
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
                  label: 'Retailers',
                  value: '${data['retailers']}',
                  icon: Icons.storefront_outlined,
                ),
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
              ],
            ),
            const SizedBox(height: 12),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(18),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Outstanding across the network',
                        style: Theme.of(context).textTheme.labelLarge?.copyWith(
                              color: Theme.of(context).colorScheme.onSurfaceVariant,
                            )),
                    const SizedBox(height: 6),
                    MoneyText(data['outstanding_paise'] as int, emphasise: true),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 32),
          ],
        );
      },
    );
  }
}

/// Stock, from the distributor's point of view: what is bought, what has been
/// pushed down to retailers, and what is left to sell.
class _StockCard extends StatelessWidget {
  const _StockCard({
    required this.wallet,
    required this.allocated,
    required this.usedDownstream,
  });

  final Map<String, dynamic> wallet;
  final int allocated;
  final int usedDownstream;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final total = wallet['total'] as int;
    final available = wallet['available'] as int;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.inventory_2_outlined, color: scheme.primary),
                const SizedBox(width: 8),
                Expanded(
                  child: Text('Activation stock',
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
                    child: Text('of $total left to allocate',
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
                value: total == 0 ? 0 : (total - available) / total,
                minHeight: 8,
              ),
            ),
            const Divider(height: 28),
            LabelledRow('Allocated to retailers', '$allocated'),
            LabelledRow('Used by retailers', '$usedDownstream'),
            LabelledRow('Still with retailers', '${allocated - usedDownstream}'),
          ],
        ),
      ),
    );
  }
}
