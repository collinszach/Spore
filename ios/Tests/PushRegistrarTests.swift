import XCTest
@testable import Spore

final class PushRegistrarTests: XCTestCase {
    func testHexEncodingIsLowercase() {
        let token = Data([0x00, 0xFC, 0x13, 0xAB, 0xFF])
        XCTAssertEqual(PushRegistrar.hexString(from: token), "00fc13abff")
    }

    func testRegisterPassesHexEncodedTokenToAPI() async {
        let api = MockDeviceAPI()
        let registrar = PushRegistrar(api: api)

        let token = Data([0x00, 0xfc, 0x13, 0xab, 0xff])
        await registrar.register(deviceToken: token)

        XCTAssertEqual(api.registeredTokens, ["00fc13abff"])
    }

    func testRegisterHandlesAPIFailureWithoutCrashing() async {
        let api = MockDeviceAPI(shouldFail: true)
        let registrar = PushRegistrar(api: api)

        let token = Data([0x01, 0x02, 0x03])
        await registrar.register(deviceToken: token)

        // No throw, no crash — failure is logged and swallowed.
        XCTAssertEqual(api.registeredTokens, ["010203"])
    }

    func testEmptyTokenEncodesToEmptyString() {
        XCTAssertEqual(PushRegistrar.hexString(from: Data()), "")
    }
}
