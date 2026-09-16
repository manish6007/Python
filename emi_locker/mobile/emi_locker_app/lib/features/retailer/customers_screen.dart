import 'package:flutter/material.dart';

import '../../core/money.dart';
import '../../core/widgets.dart';
import '../../main.dart';
import 'add_customer_screen.dart';
import 'customer_detail_screen.dart';

class CustomersScreen extends StatefulWidget {
  const CustomersScreen({super.key});

  @override
  State<CustomersScreen> createState() => _CustomersScreenState();
}

class _CustomersScreenState extends State<CustomersScreen> {
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
    return Scaffold(
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
            child: TextField(
              controller: _search,
              decoration: InputDecoration(
                hintText: 'Search name or mobile',
                prefixIcon: const Icon(Icons.search),
                suffixIcon: _query.isEmpty
                    ? null
                    : IconButton(
                        icon: const Icon(Icons.clear),
                        onPressed: () {
                          _search.clear();
                          setState(() => _query = '');
                          _viewKey.currentState?.reload();
                        },
                      ),
              ),
              onChanged: (value) => setState(() => _query = value),
              onSubmitted: (_) => _viewKey.currentState?.reload(),
            ),
          ),
          Expanded(
            child: AsyncView<Map<String, dynamic>>(
              key: _viewKey,
              load: () async => Map<String, dynamic>.from(
                await session.api.get('/retailer/customers',
                    query: {'q': _query}) as Map,
              ),
              builder: (context, data, reload) {
                final customers = List<Map<String, dynamic>>.from(
                  (data['customers'] as List)
                      .map((e) => Map<String, dynamic>.from(e as Map)),
                );
                if (customers.isEmpty) {
                  return ListView(
                    children: [
                      const SizedBox(height: 80),
                      EmptyState(
                        icon: Icons.person_add_alt,
                        title: _query.isEmpty
                            ? 'No customers yet'
                            : 'No match for "$_query"',
                        subtitle: _query.isEmpty
                            ? 'Add your first customer to start a finance.'
                            : null,
                      ),
                    ],
                  );
                }
                return ListView.separated(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 96),
                  itemCount: customers.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 10),
                  itemBuilder: (context, index) {
                    final customer = customers[index];
                    final outstanding = customer['outstanding_paise'] as int;
                    return Card(
                      child: ListTile(
                        leading: CircleAvatar(
                          child: Text((customer['name'].toString())
                              .characters
                              .first
                              .toUpperCase()),
                        ),
                        title: Text(customer['name'].toString(),
                            style: const TextStyle(fontWeight: FontWeight.w600)),
                        subtitle: Text(
                          '+91 ${customer['mobile']} • '
                          '${customer['finance_count']} finance'
                          '${customer['finance_count'] == 1 ? '' : 's'}',
                        ),
                        trailing: outstanding > 0
                            ? Column(
                                mainAxisAlignment: MainAxisAlignment.center,
                                crossAxisAlignment: CrossAxisAlignment.end,
                                children: [
                                  Text(Money.format(outstanding),
                                      style: const TextStyle(
                                          fontWeight: FontWeight.w700)),
                                  Text('due',
                                      style:
                                          Theme.of(context).textTheme.bodySmall),
                                ],
                              )
                            : const Icon(Icons.chevron_right),
                        onTap: () async {
                          await Navigator.of(context).push(MaterialPageRoute(
                            builder: (_) => CustomerDetailScreen(
                                customerId: customer['id'].toString()),
                          ));
                          await reload();
                        },
                      ),
                    );
                  },
                );
              },
            ),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () async {
          final added = await Navigator.of(context).push<String>(
            MaterialPageRoute(builder: (_) => const AddCustomerScreen()),
          );
          if (added != null) _viewKey.currentState?.reload();
        },
        icon: const Icon(Icons.person_add),
        label: const Text('Add customer'),
      ),
    );
  }
}
