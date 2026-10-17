local ip = lighty.env["request.remote-ip"]
if ip and ip ~= "" then
    lighty.header["Remote_Addr"] = ip
end
return 0
