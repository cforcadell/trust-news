// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@chainlink/contracts/src/v0.8/ChainlinkClient.sol";

contract ApiExtraerConsumer is ChainlinkClient {
    using Chainlink for Chainlink.Request;

    uint256 public message;
    address private oracle;
    bytes32 private jobId;
    uint256 private fee;

    constructor(address _link, address _oracle, bytes32 _jobId, uint256 _fee) {
        setChainlinkToken(_link);
        oracle = _oracle;
        jobId = _jobId;
        fee = _fee;
    }

    function requestExtraccion(string memory texto) public returns (bytes32 requestId) {
        Chainlink.Request memory req = buildChainlinkRequest(
            jobId,
            address(this),
            this.fulfill.selector
        );

        // 🔹 Parámetro que tu API espera en el body
        req.add("post", "http://host.docker.internal:8071/extraer"); // el nodo Chainlink ve tu API local por este hostname
        req.add("requestType", "POST");
        req.add("headers", "Content-Type: application/json");
        req.add("body", string(abi.encodePacked("{\"texto\":\"", texto, "\"}")));

        // 🔹 Ruta en el JSON devuelto
        req.add("path", "resultado");

        return sendChainlinkRequestTo(oracle, req, fee);
    }

    // Callback
    function fulfill(bytes32 _requestId, uint256 _message) public recordChainlinkFulfillment(_requestId) {
        message = _message;
    }
}
