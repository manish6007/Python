import 'package:flutter/material.dart';

import '../../core/adaptive.dart';
import '../../core/api_client.dart';
import '../../core/money.dart';
import '../../core/widgets.dart';
import '../../main.dart';

class AdminDashboard extends StatelessWidget {
  const AdminDashboard({super.key});

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    return AsyncView<List<dynamic>>(
      load: () => Future.wait([
        session.api.get('/reports/dashboard'),
        session.api.get('/reports/overdue'),
        session.api.get('/reports/retailers'),
      ]),
      builder: (context, data, reload) {
        final stats = Map<String, dynamic>.from(data[0] as Map);
        final overdue = List<Map<String, dynamic>>.from(
            ((data[1] as Map)['rows'] as List)
                .map((e) => Map<String, dynamic>.from(e as Map)));
        final retailers = List<Map<String, dynamic>>.from(
            ((data[2] as Map)['rows'] as List)
                .map((e) => Map<String, dynamic>.from(e as Map)));
        final scheme = Theme.of(context).colorScheme;
        final width = MediaQuery.sizeOf(context).width;
        final columns = width >= 1200 ? 4 : (width >= 700 ? 3 : 2);

        return ListView(
          padding: const EdgeInsets.all(20),
          children: [
            PageBody(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  GridView.count(
                    crossAxisCount: columns,
                    shrinkWrap: true,
                    physics: const NeverScrollableScrollPhysics(),
                    mainAxisSpacing: 14,
                    crossAxisSpacing: 14,
                    childAspectRatio: 1.5,
                    children: [
                      StatTile(
                          label: 'Collected',
                          value: Money.format(stats['collected_paise'] as int),
                          icon: Icons.south_west),
                      StatTile(
                          label: 'Outstanding',
                          value: Money.format(stats['outstanding_paise'] as int),
                          icon: Icons.account_balance_wallet_outlined),
                      StatTile(
                          label: 'Customers',
                          value: '${stats['customers']}',
                          icon: Icons.people_outline),
                      StatTile(
                          label: 'Active finance',
                          value: '${stats['active_finance']}',
                          icon: Icons.check_circle_outline),
                      StatTile(
                          label: 'Overdue accounts',
                          value: '${stats['overdue_finance']}',
                          icon: Icons.warning_amber_outlined,
                          tone: (stats['overdue_finance'] as int) > 0
                              ? scheme.error
                              : null),
                      StatTile(
                          label: 'Completed',
                          value: '${stats['completed_finance']}',
                          icon: Icons.verified_outlined),
                      StatTile(
                          label: 'Retailers',
                          value: '${stats['retailers']}',
                          icon: Icons.storefront_outlined),
                      StatTile(
                          label: 'Distributors',
                          value: '${stats['distributors']}',
                          icon: Icons.account_tree_outlined),
                      StatTile(
                          label: 'Activations used',
                          value: '${stats['activations_used']}',
                          icon: Icons.key_outlined),
                      StatTile(
                          label: 'Activations free',
                          value: '${stats['activations_available']}',
                          icon: Icons.inventory_2_outlined),
                      StatTile(
                          label: 'Devices restricted',
                          value: '${stats['devices_restricted']}',
                          icon: Icons.lock_outline,
                          tone: (stats['devices_restricted'] as int) > 0
                              ? scheme.error
                              : null),
                    ],
                  ),
                  const SizedBox(height: 28),
                  Row(
                    children: [
                      Expanded(
                        child: Text('Overdue accounts',
                            style: Theme.of(context).textTheme.titleMedium),
                      ),
                      OutlinedButton.icon(
                        style: OutlinedButton.styleFrom(
                            minimumSize: const Size(0, 40)),
                        onPressed: () async {
                          try {
                            final out = await session.api
                                .post('/admin/run-daily-sweep') as Map;
                            final moved =
                                Map<String, dynamic>.from(out['moved'] as Map);
                            if (!context.mounted) return;
                            showOk(context,
                                'Sweep done — due ${moved['DUE']}, grace '
                                '${moved['GRACE_PERIOD']}, overdue ${moved['OVERDUE']}');
                            await reload();
                          } on ApiException catch (error) {
                            if (context.mounted) showError(context, error);
                          }
                        },
                        icon: const Icon(Icons.update, size: 18),
                        label: const Text('Run daily sweep'),
                      ),
                    ],
                  ),
                  const SizedBox(height: 10),
                  RecordTable(
                    emptyMessage: 'No account is past its grace period',
                    columns: const [
                      'Finance',
                      'Instalments',
                      'Amount',
                      'Oldest due',
                      'Days late'
                    ],
                    rows: [
                      for (final row in overdue)
                        [
                          Text(row['finance_id'].toString()),
                          Text('${row['overdue_count']}'),
                          Text(Money.format(row['overdue_amount'] as int)),
                          Text(formatDate(row['oldest_due']?.toString())),
                          Text('${row['days_past_due']}'),
                        ],
                    ],
                  ),
                  const SizedBox(height: 28),
                  Text('Retailer performance',
                      style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 10),
                  RecordTable(
                    columns: const [
                      'Retailer',
                      'Customers',
                      'Finances',
                      'Overdue',
                      'Completed',
                      'Financed'
                    ],
                    rows: [
                      for (final row in retailers)
                        [
                          Text(row['retailer_name'].toString()),
                          Text('${row['customers']}'),
                          Text('${row['finance_count']}'),
                          Text('${row['overdue_accounts']}'),
                          Text('${row['completed']}'),
                          Text(Money.format(row['financed_paise'] as int? ?? 0)),
                        ],
                    ],
                  ),
                  const SizedBox(height: 40),
                ],
              ),
            ),
          ],
        );
      },
    );
  }
}
