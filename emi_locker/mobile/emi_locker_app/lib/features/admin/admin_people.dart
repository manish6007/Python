import 'package:flutter/material.dart';

import '../../core/adaptive.dart';
import '../../core/money.dart';
import '../../core/widgets.dart';
import '../../main.dart';

/// Every customer on the platform, across all retailers.
class AdminPeople extends StatefulWidget {
  const AdminPeople({super.key});

  @override
  State<AdminPeople> createState() => _AdminPeopleState();
}

class _AdminPeopleState extends State<AdminPeople> {
  final _search = TextEditingController();
  final _viewKey = GlobalKey<AsyncViewState<Map<String, dynamic>>>();
  String _query = '';

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        PageBody(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              SizedBox(
                width: 380,
                child: TextField(
                  controller: _search,
                  decoration: const InputDecoration(
                    hintText: 'Search name or mobile',
                    prefixIcon: Icon(Icons.search),
                  ),
                  onChanged: (value) => setState(() => _query = value),
                  onSubmitted: (_) => _viewKey.currentState?.reload(),
                ),
              ),
              const SizedBox(height: 16),
              SizedBox(
                height: MediaQuery.sizeOf(context).height * 0.7,
                child: AsyncView<Map<String, dynamic>>(
                  key: _viewKey,
                  load: () async => Map<String, dynamic>.from(
                    await session.api
                        .get('/admin/customers', query: {'q': _query}) as Map,
                  ),
                  builder: (context, data, reload) {
                    final customers = List<Map<String, dynamic>>.from(
                        (data['customers'] as List)
                            .map((e) => Map<String, dynamic>.from(e as Map)));
                    return ListView(
                      children: [
                        RecordTable(
                          emptyMessage: _query.isEmpty
                              ? 'No customers registered yet'
                              : 'Nothing matches "$_query"',
                          columns: const [
                            'Customer',
                            'Mobile',
                            'Retailer',
                            'KYC',
                            'Finances',
                            'Outstanding',
                            'Joined'
                          ],
                          rows: [
                            for (final customer in customers)
                              [
                                Text(customer['name'].toString()),
                                Text(customer['mobile'].toString()),
                                Text(customer['retailer_name'].toString()),
                                StatusChip(
                                    status: customer['kyc_status'].toString(),
                                    dense: true),
                                Text('${customer['finance_count']}'),
                                Text(Money.format(
                                    customer['outstanding_paise'] as int)),
                                Text(formatDate(customer['created_at']
                                    ?.toString()
                                    .split('T')
                                    .first)),
                              ],
                          ],
                        ),
                      ],
                    );
                  },
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
