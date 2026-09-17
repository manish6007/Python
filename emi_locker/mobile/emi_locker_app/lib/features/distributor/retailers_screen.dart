import 'package:flutter/material.dart';

import '../../core/money.dart';
import '../../core/widgets.dart';
import '../../main.dart';
import 'retailer_detail_screen.dart';

class RetailersScreen extends StatelessWidget {
  const RetailersScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    return AsyncView<Map<String, dynamic>>(
      load: () async => Map<String, dynamic>.from(
          await session.api.get('/distributor/retailers') as Map),
      builder: (context, data, reload) {
        final retailers = List<Map<String, dynamic>>.from(
            (data['retailers'] as List).map((e) => Map<String, dynamic>.from(e as Map)));
        if (retailers.isEmpty) {
          return ListView(
            children: const [
              SizedBox(height: 100),
              EmptyState(
                icon: Icons.storefront_outlined,
                title: 'No retailers yet',
                subtitle:
                    'Retailers are created by the head office and assigned to '
                    'you. Once assigned, they appear here.',
              ),
            ],
          );
        }
        return ListView.separated(
          padding: const EdgeInsets.all(16),
          itemCount: retailers.length,
          separatorBuilder: (_, __) => const SizedBox(height: 12),
          itemBuilder: (context, index) {
            final retailer = retailers[index];
            final available = retailer['available_quota'] as int;
            final scheme = Theme.of(context).colorScheme;
            return Card(
              child: InkWell(
                borderRadius: BorderRadius.circular(16),
                onTap: () async {
                  await Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => RetailerDetailScreen(
                      retailerId: retailer['id'].toString(),
                      retailerName: retailer['name'].toString(),
                    ),
                  ));
                  await reload();
                },
                child: Padding(
                  padding: const EdgeInsets.all(18),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          CircleAvatar(
                            child: Text(retailer['name']
                                .toString()
                                .characters
                                .first
                                .toUpperCase()),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(retailer['name'].toString(),
                                    style: const TextStyle(
                                        fontWeight: FontWeight.w600, fontSize: 16)),
                                Text('+91 ${retailer['mobile'] ?? '-'}',
                                    style: Theme.of(context)
                                        .textTheme
                                        .bodySmall
                                        ?.copyWith(color: scheme.onSurfaceVariant)),
                              ],
                            ),
                          ),
                          if (retailer['status'] != 'ACTIVE')
                            StatusChip(status: retailer['status'].toString(), dense: true),
                        ],
                      ),
                      const Divider(height: 24),
                      Row(
                        children: [
                          Expanded(
                            child: _Metric(
                              label: 'Activations left',
                              value: '$available',
                              tone: available == 0 ? scheme.error : null,
                            ),
                          ),
                          Expanded(
                            child: _Metric(
                              label: 'Outstanding',
                              value: Money.format(
                                  retailer['outstanding_paise'] as int),
                            ),
                          ),
                          Expanded(
                            child: _Metric(
                              label: 'Overdue',
                              value: '${retailer['overdue_finance']}',
                              tone: (retailer['overdue_finance'] as int) > 0
                                  ? scheme.error
                                  : null,
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            );
          },
        );
      },
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value, this.tone});

  final String label;
  final String value;
  final Color? tone;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
            maxLines: 2,
            overflow: TextOverflow.ellipsis),
        const SizedBox(height: 4),
        FittedBox(
          fit: BoxFit.scaleDown,
          alignment: Alignment.centerLeft,
          child: Text(value,
              maxLines: 1,
              style: Theme.of(context)
                  .textTheme
                  .titleMedium
                  ?.copyWith(fontWeight: FontWeight.w700, color: tone)),
        ),
      ],
    );
  }
}
