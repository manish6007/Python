import 'package:flutter/material.dart';

import '../../core/widgets.dart';
import '../../main.dart';

class CustomerProfile extends StatelessWidget {
  const CustomerProfile({super.key});

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    return AsyncView<Map<String, dynamic>>(
      load: () async =>
          Map<String, dynamic>.from(await session.api.get('/me/profile') as Map),
      builder: (context, profile, reload) {
        final retailer = profile['retailer'] as Map?;
        final missing = List<String>.from(
            (profile['missing_consents'] as List? ?? []).map((e) => e.toString()));
        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(18),
                child: Column(
                  children: [
                    CircleAvatar(
                      radius: 32,
                      child: Text(
                        (profile['name']?.toString() ?? '?')
                            .characters
                            .first
                            .toUpperCase(),
                        style: const TextStyle(fontSize: 24),
                      ),
                    ),
                    const SizedBox(height: 12),
                    Text(profile['name'].toString(),
                        style: Theme.of(context).textTheme.titleMedium),
                    Text('+91 ${profile['mobile']}',
                        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                              color: Theme.of(context).colorScheme.onSurfaceVariant,
                            )),
                    const Divider(height: 28),
                    LabelledRow('Customer ID', profile['id'].toString()),
                    LabelledRow('Address', profile['address']?.toString() ?? '-'),
                    LabelledRow('KYC status', profile['kyc_status'].toString()),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 16),
            if (retailer != null)
              Card(
                child: ListTile(
                  leading: const Icon(Icons.storefront_outlined),
                  title: Text(retailer['name'].toString()),
                  subtitle: Text(
                    retailer['mobile'] == null
                        ? 'Your retailer'
                        : 'Your retailer • +91 ${retailer['mobile']}',
                  ),
                ),
              ),
            if (missing.isNotEmpty) ...[
              const SizedBox(height: 16),
              Card(
                color: Theme.of(context).colorScheme.errorContainer,
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Text(
                    'Consent still to be recorded: ${missing.join(', ')}',
                    style: TextStyle(
                        color: Theme.of(context).colorScheme.onErrorContainer),
                  ),
                ),
              ),
            ],
            const SizedBox(height: 24),
            OutlinedButton.icon(
              onPressed: session.signOut,
              icon: const Icon(Icons.logout),
              label: const Text('Sign out'),
            ),
          ],
        );
      },
    );
  }
}
