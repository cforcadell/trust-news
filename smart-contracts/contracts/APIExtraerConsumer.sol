// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import "@chainlink/contracts/src/v0.8/ChainlinkClient.sol";

/// @title ApiExtraerConsumer
/// @notice Solicita a un Chainlink Node la extracción de aserciones de un texto
contract ApiExtraerConsumer is ChainlinkClient {
    using Chainlink for Chainlink.Request;

    string public message;           // Resultado de la API como string
    address private oracle;
    bytes32 private jobId;
    uint256 private fee;

    bytes32 public lastRequestId;

    /// @param _link Dirección del token LINK
    /// @param _oracle Dirección del Oracle (Operator)
    /// @param _jobId JobId del Chainlink Node en bytes32
    /// @param _fee Fee en LINK (18 decimales)
    constructor(address _link, address _oracle, bytes32 _jobId, uint256 _fee) {
        setChainlinkToken(_link);
        oracle = _oracle;
        jobId = _jobId;
        fee = _fee;
    }

    /// @notice Envía un request al Chainlink Node
    function requestExtraccion(string memory texto) public returns (bytes32 requestId) {
        Chainlink.Request memory req = buildChainlinkRequest(
            jobId,
            address(this),
            this.fulfill.selector
        );

        req.add("post", "http://generate-asertions:8071/extraer"); // URL de tu API
        req.add("requestType", "POST");
        req.add("headers", "Content-Type: application/json");
        req.add("body", string(abi.encodePacked("{\"texto\":\"", texto, "\"}")));

        req.add("path", "aserciones"); // campo JSON que devuelve tu API

        requestId = sendChainlinkRequestTo(oracle, req, fee);
        lastRequestId = requestId;
    }

    /// @notice Callback que recibe los datos en bytes del Chainlink Node
    function fulfill(bytes32 _requestId, bytes memory _aserciones)
        public
        recordChainlinkFulfillment(_requestId)
    {
        message = string(_aserciones);
    }
}
