import Flutter
import GoogleMaps
import UIKit

@main
@objc class AppDelegate: FlutterAppDelegate {
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    let envKey = ProcessInfo.processInfo.environment["GOOGLE_MAPS_API_KEY"] ?? ""
    let plistKey =
      (Bundle.main.object(forInfoDictionaryKey: "GMSApiKey") as? String) ?? ""
    let key = envKey.isEmpty ? plistKey : envKey
    if !key.isEmpty {
      GMSServices.provideAPIKey(key)
    }
    GeneratedPluginRegistrant.register(with: self)
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }
}
