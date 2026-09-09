import 'package:commute_agent/data/places_api_client.dart';
import 'package:commute_agent/data/repositories/commute_repository_impl.dart';
import 'package:commute_agent/domain/entities/commute_request.dart';
import 'package:commute_agent/domain/entities/user_preferences.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  group('Phase 7I — Places client', () {
    test('parses autocomplete suggestions', () async {
      final client = PlacesApiClient(
        httpClient: MockClient((request) async {
          expect(request.url.path, endsWith('/places/autocomplete'));
          expect(request.url.queryParameters['q'], 'Kora');
          return http.Response(
            '''
            {
              "ok": true,
              "suggestions": [
                {
                  "place_id": "pid_1",
                  "description": "Koramangala, Bengaluru",
                  "main_text": "Koramangala",
                  "secondary_text": "Bengaluru"
                }
              ],
              "error": null
            }
            ''',
            200,
          );
        }),
      );
      final list = await client.autocomplete(
        baseUrl: 'http://test',
        query: 'Kora',
      );
      expect(list, hasLength(1));
      expect(list.first.placeId, 'pid_1');
      expect(list.first.mainText, 'Koramangala');
    });

    test('parses place details lat/lon', () async {
      final client = PlacesApiClient(
        httpClient: MockClient((request) async {
          expect(request.url.path, endsWith('/places/details'));
          return http.Response(
            '''
            {
              "ok": true,
              "place": {
                "place_id": "pid_1",
                "name": "Koramangala",
                "formatted_address": "Koramangala, Bengaluru",
                "latitude": 12.9352,
                "longitude": 77.6245
              }
            }
            ''',
            200,
          );
        }),
      );
      final place = await client.details(
        baseUrl: 'http://test',
        placeId: 'pid_1',
      );
      expect(place, isNotNull);
      expect(place!.latitude, closeTo(12.9352, 0.0001));
      expect(place.longitude, closeTo(77.6245, 0.0001));
    });
  });

  group('Phase 7I — plan body includes coordinates', () {
    test('origin/destination lat lon serialized when present', () {
      final repo = CommuteRepositoryImpl(baseUrl: 'http://test');
      final body = repo.buildPlanRequestBody(
        const CommuteRequest(
          origin: 'Koramangala',
          destination: 'Indiranagar',
          preferences: UserPreferences(),
          originLat: 12.9352,
          originLon: 77.6245,
          destinationLat: 12.9784,
          destinationLon: 77.6408,
        ),
      );
      expect(body['origin_lat'], 12.9352);
      expect(body['origin_lon'], 77.6245);
      expect(body['destination_lat'], 12.9784);
      expect(body['destination_lon'], 77.6408);
    });

    test('omits coords when not selected', () {
      final repo = CommuteRepositoryImpl(baseUrl: 'http://test');
      final body = repo.buildPlanRequestBody(
        const CommuteRequest(
          origin: 'Koramangala',
          destination: 'Indiranagar',
          preferences: UserPreferences(),
        ),
      );
      expect(body.containsKey('origin_lat'), isFalse);
      expect(body.containsKey('destination_lat'), isFalse);
    });
  });
}
