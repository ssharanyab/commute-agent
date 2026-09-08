import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'presentation/providers/commute_provider.dart';
import 'presentation/screens/home/planner_page.dart';

void main() {
  runApp(const CommuteAgentApp());
}

class CommuteAgentApp extends StatelessWidget {
  const CommuteAgentApp({super.key});

  @override
  Widget build(BuildContext context) {
    final base = ThemeData(
      useMaterial3: true,
      colorScheme: ColorScheme.fromSeed(
        seedColor: const Color(0xFF0F6E56),
        brightness: Brightness.light,
      ),
    );
    return ChangeNotifierProvider(
      create: (_) => CommuteProvider(),
      child: MaterialApp(
        title: 'Patchamomma Commute',
        debugShowCheckedModeBanner: false,
        theme: base.copyWith(
          inputDecorationTheme: const InputDecorationTheme(
            border: OutlineInputBorder(),
            isDense: true,
          ),
          filledButtonTheme: FilledButtonThemeData(
            style: FilledButton.styleFrom(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
            ),
          ),
        ),
        home: const PlannerPage(),
      ),
    );
  }
}
