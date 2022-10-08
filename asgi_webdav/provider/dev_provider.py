import urllib.parse
from collections.abc import AsyncGenerator
from logging import getLogger

from asgi_webdav.config import Config
from asgi_webdav.constants import DAV_METHODS, DAVLockInfo, DAVPath, DAVPropertyIdentity
from asgi_webdav.helpers import dav_dict2xml, receive_all_data_in_one_call
from asgi_webdav.lock import DAVLock
from asgi_webdav.property import DAVProperty, DAVPropertyBasicData
from asgi_webdav.request import DAVRequest
from asgi_webdav.response import DAVResponse, DAVResponseType

logger = getLogger(__name__)


class DAVProvider:
    def __init__(
        self,
        config: Config,
        prefix: DAVPath,
        uri: str,
        home_dir: bool = False,
        read_only: bool = False,
    ):
        self.config = config

        self.prefix = prefix
        self.uri = uri

        self.home_dir = home_dir
        self.read_only = read_only  # TODO

        self.dav_lock = DAVLock()

        # https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Headers/Accept-Ranges
        self.support_content_range: bool = False

    def __repr__(self):
        raise NotImplementedError

    @staticmethod
    def _create_ns_key_with_id(ns_map: dict[str, str], ns: str, key: str) -> str:
        if len(ns) == 0:
            # no namespace
            return key

        ns_id = ns_map.setdefault(ns, f"ns{len(ns_map) + 1}")
        return f"{ns_id}:{key}"

    @staticmethod
    def _create_data_lock_discovery(lock_info: DAVLockInfo) -> dict:
        return {
            "D:activelock": {
                "D:locktype": {"D:write": None},
                "D:lockscope": {f"D:{lock_info.lock_scope.name}": None},
                "D:depth": lock_info.depth.value,
                "D:owner": lock_info.owner,
                "D:timeout": f"Second-{lock_info.timeout}",
                "D:locktoken": {
                    "D:href": f"opaquelocktoken:{lock_info.token}",
                },
            },
        }

    """
    https://tools.ietf.org/html/rfc4918#page-35
    9.1.1.  PROPFIND Status Codes
    
       This section, as with similar sections for other methods, provides
       some guidance on error codes and preconditions or postconditions
       (defined in Section 16) that might be particularly useful with
       PROPFIND.
    
       403 Forbidden - A server MAY reject PROPFIND requests on collections
       with depth header of "Infinity", in which case it SHOULD use this
       error with the precondition code 'propfind-finite-depth' inside the
       error body.
    
    9.1.2.  Status Codes for Use in 'propstat' Element
    
       In PROPFIND responses, information about individual properties_list is
       returned inside 'propstat' elements (see Section 14.22), each
       containing an individual 'status' element containing information
       about the properties_list appearing in it. The list below summarizes the
       most common status codes used inside 'propstat'; however, clients
       should be prepared to handle other 2/3/4/5xx series status codes as
       well.
    
       200 OK - A property exists and/or its value is successfully returned.
    
       401 Unauthorized - The property cannot be viewed without appropriate
       authorization.
    
       403 Forbidden - The property cannot be viewed regardless of
       authentication.
    
       404 Not Found - The property does not exist.
    
    https://www.rfc-editor.org/rfc/rfc4918#section-11
    11.  Status Code Extensions to HTTP/1.1
    
       The following status codes are added to those defined in HTTP/1.1
       [RFC2616].
    
    11.1.  207 Multi-Status
    
       The 207 (Multi-Status) status code provides status for multiple
       independent operations (see Section 13 for more information).
    
    11.2.  422 Unprocessable Entity
    
       The 422 (Unprocessable Entity) status code means the server
       understands the content type of the request entity (hence a
       415(Unsupported Media Type) status code is inappropriate), and the
       syntax of the request entity is correct (thus a 400 (Bad Request)
       status code is inappropriate) but was unable to process the contained
       instructions.  For example, this error condition may occur if an XML
       request body contains well-formed (i.e., syntactically correct), but
       semantically erroneous, XML instructions.
    
    11.3.  423 Locked
    
       The 423 (Locked) status code means the source or destination resource
       of a method is locked.  This response SHOULD contain an appropriate
       precondition or postcondition code, such as 'lock-token-submitted' or
       'no-conflicting-lock'.
       
   11.4.  424 Failed Dependency

       The 424 (Failed Dependency) status code means that the method could
       not be performed on the resource because the requested action
       depended on another action and that action failed.  For example, if a
       command in a PROPPATCH method fails, then, at minimum, the rest of
       the commands will also fail with 424 (Failed Dependency).
    
    11.5.  507 Insufficient Storage
    
       The 507 (Insufficient Storage) status code means the method could not
       be performed on the resource because the server is unable to store
       the representation needed to successfully complete the request.  This
       condition is considered to be temporary.  If the request that
       received this status code was the result of a user action, the
       request MUST NOT be repeated until it is requested by a separate user
       action.
    """

    async def do_propfind(self, request: DAVRequest) -> dict[DAVPath, DAVProperty]:
        # len(dav_properties) == 0 --> 404 Not Found
        return await self._do_propfind(request)

    async def _do_propfind(self, request: DAVRequest) -> dict[DAVPath, DAVProperty]:
        raise NotImplementedError

    async def create_propfind_response(
        self, request: DAVRequest, dav_properties: dict[DAVPath, DAVProperty]
    ) -> bytes:
        response = list()
        ns_map = dict()
        for dav_property in dav_properties.values():
            href_path = dav_property.href_path

            found_property = dict()
            # basic data
            property_basic_data = dav_property.basic_data.as_dict()
            if request.propfind_fetch_all_property:
                basic_keys = property_basic_data.keys()
            else:
                basic_keys = request.propfind_basic_keys

            for k in basic_keys:
                if k in property_basic_data:
                    found_property["D:" + k] = property_basic_data[k]

            if dav_property.is_collection:
                found_property["D:resourcetype"] = {"D:collection": None}
            else:
                found_property["D:resourcetype"] = None

            # extra data
            for (ns, key), value in dav_property.extra_data.items():
                ns_id = self._create_ns_key_with_id(ns_map, ns, key)
                found_property[ns_id] = value

            # lock
            lock_info = await self.dav_lock.get_info_by_path(href_path)
            if len(lock_info) > 0:
                # TODO!!!! multi-token
                lock_discovery = self._create_data_lock_discovery(lock_info[0])
            else:
                lock_discovery = None

            # found_property.update(
            #     {
            #         "D:supportedlock": {
            #             "D:lockentry": [
            #                 {
            #                     "D:lockscope": {"D:exclusive": None},
            #                     "D:locktype": {"D:write": None},
            #                 },
            #                 {
            #                     "D:lockscope": {"D:shared": None},
            #                     "D:locktype": {"D:write": None},
            #                 },
            #             ]
            #         }
            #     }
            # )

            response_item = {
                "D:href": urllib.parse.quote(href_path.raw, encoding="utf-8"),
                "D:propstat": [
                    {
                        "D:prop": found_property,
                        "D:lockdiscovery": lock_discovery,
                        "D:status": "HTTP/1.1 200 OK",
                    },
                ],
            }

            # extra not found
            if len(dav_property.extra_not_found) > 0:
                not_found_property = dict()
                for ns, key in dav_property.extra_not_found:
                    ns_id = self._create_ns_key_with_id(ns_map, ns, key)
                    not_found_property[ns_id] = None

                not_found_property = {
                    "D:prop": not_found_property,
                    "D:status": "HTTP/1.1 404 Not Found",
                }
                response_item["D:propstat"].append(not_found_property)

            # namespace
            # TODO ns0 => DAV:
            for k, v in ns_map.items():
                response_item[f"@xmlns:{v}"] = k

            response.append(response_item)

        data = {
            "D:multistatus": {
                "@xmlns:D": "DAV:",
                "D:response": response,
            }
        }
        return dav_dict2xml(data)

    """
    https://tools.ietf.org/html/rfc4918#page-44
    9.2.  PROPPATCH Method
    9.2.1.  Status Codes for Use in 'propstat' Element
    
       In PROPPATCH responses, information about individual properties_list is
       returned inside 'propstat' elements (see Section 14.22), each
       containing an individual 'status' element containing information
       about the properties_list appearing in it. The list below summarizes the
       most common status codes used inside 'propstat'; however, clients
       should be prepared to handle other 2/3/4/5xx series status codes as
       well.
    
       200 (OK) - The property set or change succeeded.  Note that if this
       appears for one property, it appears for every property in the
       response, due to the atomicity of PROPPATCH.
    
       403 (Forbidden) - The client, for reasons the server chooses not to
       specify, cannot alter one of the properties_list.
    
       403 (Forbidden): The client has attempted to set a protected
       property, such as DAV:getetag.  If returning this error, the server
       SHOULD use the precondition code 'cannot-modify-protected-property'
       inside the response body.
    
       409 (Conflict) - The client has provided a value whose semantics are
       not appropriate for the property.
    
       424 (Failed Dependency) - The property change could not be made
       because of another property change that failed.
    
       507 (Insufficient Storage) - The server did not have sufficient space
       to record the property.
    """

    async def do_proppatch(self, request: DAVRequest) -> DAVResponse:
        if not request.body_is_parsed_success:
            return DAVResponse(400)

        if await self.dav_lock.is_locking(request.src_path, request.lock_token):
            return DAVResponse(423)

        http_status = await self._do_proppatch(request)
        if http_status == 207:
            sucess_ids = [x[0] for x in request.proppatch_entries]
            message = self._create_proppatch_response(request, sucess_ids)
        else:
            message = b""

        return DAVResponse(
            http_status, content=message, response_type=DAVResponseType.XML
        )

    async def _do_proppatch(self, request: DAVRequest) -> int:
        raise NotImplementedError

    @staticmethod
    def _create_proppatch_response(
        request: DAVRequest, sucess_ids: list[DAVPropertyIdentity]
    ) -> bytes:
        data = dict()
        for ns, key in sucess_ids:
            # data['ns1:{}'.format(item)] = None
            data[f"D:{key}"] = None  # TODO namespace

        data = {
            "D:multistatus": {
                "@xmlns:D": "DAV:",
                "D:response": {
                    "D:href": request.src_path,
                    "D:propstat": {
                        "D:prop": data,
                        "D:status": "HTTP/1.1 200 OK",
                    },
                },
            }
        }
        return dav_dict2xml(data)

    """
    https://tools.ietf.org/html/rfc4918#page-46
    9.3.1.  MKCOL Status Codes
    
       In addition to the general status codes possible, the following
       status codes have specific applicability to MKCOL:
    
       201 (Created) - The collection was created.
    
       403 (Forbidden) - This indicates at least one of two conditions: 1)
       the server does not allow the creation of collections at the given
       location in its URL namespace, or 2) the parent collection of the
       Request-URI exists but cannot accept members.
    
       405 (Method Not Allowed) - MKCOL can only be executed on an unmapped
       URL.
    
       409 (Conflict) - A collection cannot be made at the Request-URI until
       one or more intermediate collections have been created.  The server
       MUST NOT create those intermediate collections automatically.
    
       415 (Unsupported Media Type) - The server does not support the
       request body type (although bodies are legal on MKCOL requests, since
       this specification doesn't define any, the server is likely not to
       support any given body type).
    
       507 (Insufficient Storage) - The resource does not have sufficient
       space to record the state of the resource after the execution of this
       method.
    """

    async def do_mkcol(self, request: DAVRequest) -> DAVResponse:
        request_data = await receive_all_data_in_one_call(request.receive)
        if len(request_data) > 0:
            # https://tools.ietf.org/html/rfc2518#page-33
            # https://tools.ietf.org/html/rfc4918#page-46
            return DAVResponse(415)

        http_status = await self._do_mkcol(request)
        return DAVResponse(http_status)

    async def _do_mkcol(self, request: DAVRequest) -> int:
        raise NotImplementedError

    """
    https://tools.ietf.org/html/rfc4918#page-48
    9.4.  GET, HEAD for Collections
    
       The semantics of GET are unchanged when applied to a collection,
       since GET is defined as, "retrieve whatever information (in the form
       of an entity) is identified by the Request-URI" [RFC2616].  GET, when
       applied to a collection, may return the contents of an "index.html"
       resource, a human-readable view of the contents of the collection, or
       something else altogether.  Hence, it is possible that the result of
       a GET on a collection will bear no correlation to the membership of
       the collection.
    
       Similarly, since the definition of HEAD is a GET without a response
       message body, the semantics of HEAD are unmodified when applied to
       collection resources.
    
    https://tools.ietf.org/html/rfc2616#page-53
    9.3 GET
    
       The GET method means retrieve whatever information (in the form of an
       entity) is identified by the Request-URI. If the Request-URI refers
       to a data-producing process, it is the produced data which shall be
       returned as the entity in the response and not the source text of the
       process, unless that text happens to be the output of the process.
    
       The semantics of the GET method change to a "conditional GET" if the
       request message includes an If-Modified-Since, If-Unmodified-Since,
       If-Match, If-None-Match, or If-Range header field. A conditional GET
       method requests that the entity be transferred only under the
       circumstances described by the conditional header field(s). The
       conditional GET method is intended to reduce unnecessary network
       usage by allowing cached entities to be refreshed without requiring
       multiple requests or transferring data already held by the client.
    
       The semantics of the GET method change to a "partial GET" if the
       request message includes a Range header field. A partial GET requests
       that only part of the entity be transferred, as described in section
       14.35. The partial GET method is intended to reduce unnecessary
       network usage by allowing partially-retrieved entities to be
       completed without transferring data already held by the client.
    
       The response to a GET request is cacheable if and only if it meets
       the requirements for HTTP caching described in section 13.
    
       See section 15.1.3 for security considerations when used for forms.
       
    https://datatracker.ietf.org/doc/html/rfc7233#section-4.2
    4.2.  Content-Range

       The "Content-Range" header field is sent in a single part 206
       (Partial Content) response to indicate the partial range of the
       selected representation enclosed as the message payload, sent in each
       part of a multipart 206 response to indicate the range enclosed
       within each body part, and sent in 416 (Range Not Satisfiable)
       responses to provide information about the selected representation.
    
         Content-Range       = byte-content-range
                             / other-content-range
    
         byte-content-range  = bytes-unit SP
                               ( byte-range-resp / unsatisfied-range )
    
         byte-range-resp     = byte-range "/" ( complete-length / "*" )
         byte-range          = first-byte-pos "-" last-byte-pos
         unsatisfied-range   = "*/" complete-length
    
         complete-length     = 1*DIGIT
    
         other-content-range = other-range-unit SP other-range-resp
         other-range-resp    = *CHAR
    """

    async def do_get(
        self, request: DAVRequest
    ) -> tuple[int, DAVPropertyBasicData | None, AsyncGenerator | None]:
        return await self._do_get(request)

    async def _do_get(
        self, request: DAVRequest
    ) -> tuple[int, DAVPropertyBasicData | None, AsyncGenerator | None]:
        # 404, None, None
        # 200, DAVPropertyBasicData, None  # is_dir
        # 200/206, DAVPropertyBasicData, AsyncGenerator  # is_file
        #
        # self._create_get_head_response_headers()
        raise NotImplementedError

    async def do_head(self, request: DAVRequest) -> DAVResponse:
        http_status, property_basic_data = await self._do_head(request)
        if http_status == 200:
            headers = property_basic_data.get_get_head_response_headers()
            if self.support_content_range:
                headers.update(
                    {
                        b"Accept-Ranges": b"bytes",
                    }
                )
            response = DAVResponse(status=http_status, headers=headers)
        else:
            response = DAVResponse(404)  # TODO

        return response

    async def _do_head(
        self, request: DAVRequest
    ) -> tuple[int, DAVPropertyBasicData | None]:
        raise NotImplementedError

    """
    https://tools.ietf.org/html/rfc4918#page-48
    9.6.  DELETE Requirements
    
       DELETE is defined in [RFC2616], Section 9.7, to "delete the resource
       identified by the Request-URI".  However, WebDAV changes some DELETE
       handling requirements.
    
       A server processing a successful DELETE request:
    
          MUST destroy locks rooted on the deleted resource
    
          MUST remove the mapping from the Request-URI to any resource.
    
       Thus, after a successful DELETE operation (and in the absence of
       other actions), a subsequent GET/HEAD/PROPFIND request to the target
       Request-URI MUST return 404 (Not Found).
    
    9.6.1.  DELETE for Collections
    
       The DELETE method on a collection MUST act as if a "Depth: infinity"
       header was used on it.  A client MUST NOT submit a Depth header with
       a DELETE on a collection with any value but infinity.
    
       DELETE instructs that the collection specified in the Request-URI and
       all resources identified by its internal member URLs are to be
       deleted.
    
       If any resource identified by a member URL cannot be deleted, then
       all of the member's ancestors MUST NOT be deleted, so as to maintain
       URL namespace consistency.
    
       Any headers included with DELETE MUST be applied in processing every
       resource to be deleted.
    
       When the DELETE method has completed processing, it MUST result in a
       consistent URL namespace.
    
       If an error occurs deleting a member resource (a resource other than
       the resource identified in the Request-URI), then the response can be
       a 207 (Multi-Status).  Multi-Status is used here to indicate which
       internal resources could NOT be deleted, including an error code,
       which should help the client understand which resources caused the
       failure.  For example, the Multi-Status body could include a response
       with status 423 (Locked) if an internal resource was locked.
    
       The server MAY return a 4xx status response, rather than a 207, if
       the request failed completely.
    
       424 (Failed Dependency) status codes SHOULD NOT be in the 207 (Multi-
       Status) response for DELETE.  They can be safely left out because the
       client will know that the ancestors of a resource could not be
       deleted when the client receives an error for the ancestor's progeny.
       Additionally, 204 (No Content) errors SHOULD NOT be returned in the
       207 (Multi-Status).  The reason for this prohibition is that 204 (No
       Content) is the default success code.
    
    https://tools.ietf.org/html/rfc2616#section-9.7
    9.7 DELETE
    
       The DELETE method requests that the origin server delete the resource
       identified by the Request-URI. This method MAY be overridden by human
       intervention (or other means) on the origin server. The client cannot
       be guaranteed that the operation has been carried out, even if the
       status code returned from the origin server indicates that the action
       has been completed successfully. However, the server SHOULD NOT
       indicate success unless, at the time the response is given, it
       intends to delete the resource or move it to an inaccessible
       location.
    
       A successful response SHOULD be 200 (OK) if the response includes an
       entity describing the status, 202 (Accepted) if the action has not
       yet been enacted, or 204 (No Content) if the action has been enacted
       but the response does not include an entity.
    
       If the request passes through a cache and the Request-URI identifies
       one or more currently cached entities, those entries SHOULD be
       treated as stale. Responses to this method are not cacheable.
    """

    async def do_delete(self, request: DAVRequest) -> DAVResponse:
        if await self.dav_lock.is_locking(request.src_path, request.lock_token):
            return DAVResponse(423)

        http_status = await self._do_delete(request)
        if http_status == 204:
            await self.dav_lock.release(request.lock_token)

        return DAVResponse(http_status)

    async def _do_delete(self, request: DAVRequest) -> int:
        raise NotImplementedError

    """
    https://tools.ietf.org/html/rfc4918#page-50
    9.7.  PUT Requirements
    
    9.7.1.  PUT for Non-Collection Resources
    
       A PUT performed on an existing resource replaces the GET response
       entity of the resource.  Properties defined on the resource may be
       recomputed during PUT processing but are not otherwise affected.  For
       example, if a server recognizes the content type of the request body,
       it may be able to automatically extract information that could be
       profitably exposed as properties_list.
    
       A PUT that would result in the creation of a resource without an
       appropriately scoped parent collection MUST fail with a 409
       (Conflict).
    
       A PUT request allows a client to indicate what media type an entity
       body has, and whether it should change if overwritten.  Thus, a
       client SHOULD provide a Content-Type for a new resource if any is
       known.  If the client does not provide a Content-Type for a new
       resource, the server MAY create a resource with no Content-Type
       assigned, or it MAY attempt to assign a Content-Type.
    
       Note that although a recipient ought generally to treat metadata
       supplied with an HTTP request as authoritative, in practice there's
       no guarantee that a server will accept client-supplied metadata
       (e.g., any request header beginning with "Content-").  Many servers
       do not allow configuring the Content-Type on a per-resource basis in
       the first place.  Thus, clients can't always rely on the ability to
       directly influence the content type by including a Content-Type
       request header.
    
    9.7.2.  PUT for Collections
    
       This specification does not define the behavior of the PUT method for
       existing collections.  A PUT request to an existing collection MAY be
       treated as an error (405 Method Not Allowed).
    
       The MKCOL method is defined to create collections.
    """

    async def do_put(self, request: DAVRequest) -> DAVResponse:
        if not request.lock_token_is_parsed_success:
            return DAVResponse(412)

        # check etag
        if request.lock_token_etag:
            etag = await self._do_get_etag(request)
            if etag != request.lock_token_etag:
                return DAVResponse(412)

        if request.lock_token_path is None:
            locked_path = request.src_path
        else:
            locked_path = request.lock_token_path

        if await self.dav_lock.is_locking(locked_path, request.lock_token):
            return DAVResponse(423)

        http_status = await self._do_put(request)
        return DAVResponse(http_status)

    async def _do_put(self, request: DAVRequest) -> int:
        raise NotImplementedError

    async def _do_get_etag(self, request: DAVRequest) -> str:
        raise NotImplementedError

    """
    https://tools.ietf.org/html/rfc4918#page-51
    9.8.  COPY Method
    9.8.5.  Status Codes
    
       In addition to the general status codes possible, the following
       status codes have specific applicability to COPY:
    
       201 (Created) - The source resource was successfully copied.  The
       COPY operation resulted in the creation of a new resource.
    
       204 (No Content) - The source resource was successfully copied to a
       preexisting destination resource.
    
       207 (Multi-Status) - Multiple resources were to be affected by the
       COPY, but errors on some of them prevented the operation from taking
       place.  Specific error messages, together with the most appropriate
       of the source and destination URLs, appear in the body of the multi-
       status response.  For example, if a destination resource was locked
       and could not be overwritten, then the destination resource URL
       appears with the 423 (Locked) status.
    
       403 (Forbidden) - The operation is forbidden.  A special case for
       COPY could be that the source and destination resources are the same
       resource.
    
       409 (Conflict) - A resource cannot be created at the destination
       until one or more intermediate collections have been created.  The
       server MUST NOT create those intermediate collections automatically.
    
       412 (Precondition Failed) - A precondition header check failed, e.g.,
       the Overwrite header is "F" and the destination URL is already mapped
       to a resource.
    
       423 (Locked) - The destination resource, or resource within the
       destination collection, was locked.  This response SHOULD contain the
       'lock-token-submitted' precondition element.
    
       502 (Bad Gateway) - This may occur when the destination is on another
       server, repository, or URL namespace.  Either the source namespace
       does not support copying to the destination namespace, or the
       destination namespace refuses to accept the resource.  The client may
       wish to try GET/PUT and PROPFIND/PROPPATCH instead.
    
       507 (Insufficient Storage) - The destination resource does not have
       sufficient space to record the state of the resource after the
       execution of this method.
    """

    async def do_copy(self, request: DAVRequest) -> DAVResponse:
        if not request.dst_path.startswith(self.prefix):
            # Do not support between DAVProvider instance
            return DAVResponse(400)

        if request.depth is None:
            return DAVResponse(403)

        if await self.dav_lock.is_locking(request.dst_path, request.lock_token):
            return DAVResponse(423)

        http_status = await self._do_copy(request)
        return DAVResponse(http_status)

    async def _do_copy(self, request: DAVRequest) -> int:
        raise NotImplementedError

    """
    https://tools.ietf.org/html/rfc4918#page-56
    9.9.  MOVE Method
    9.9.4.  Status Codes
    
       In addition to the general status codes possible, the following
       status codes have specific applicability to MOVE:
    
       201 (Created) - The source resource was successfully moved, and a new
       URL mapping was created at the destination.
    
       204 (No Content) - The source resource was successfully moved to a
       URL that was already mapped.
    
       207 (Multi-Status) - Multiple resources were to be affected by the
       MOVE, but errors on some of them prevented the operation from taking
       place.  Specific error messages, together with the most appropriate
       of the source and destination URLs, appear in the body of the multi-
       status response.  For example, if a source resource was locked and
       could not be moved, then the source resource URL appears with the 423
       (Locked) status.
    
       403 (Forbidden) - Among many possible reasons for forbidding a MOVE
       operation, this status code is recommended for use when the source
       and destination resources are the same.
    
       409 (Conflict) - A resource cannot be created at the destination
       until one or more intermediate collections have been created.  The
       server MUST NOT create those intermediate collections automatically.
       Or, the server was unable to preserve the behavior of the live
       properties_list and still move the resource to the destination (see
       'preserved-live-properties_list' postcondition).
    
       412 (Precondition Failed) - A condition header failed.  Specific to
       MOVE, this could mean that the Overwrite header is "F" and the
       destination URL is already mapped to a resource.
    
       423 (Locked) - The source or the destination resource, the source or
       destination resource parent, or some resource within the source or
       destination collection, was locked.  This response SHOULD contain the
       'lock-token-submitted' precondition element.
    
       502 (Bad Gateway) - This may occur when the destination is on another
       server and the destination server refuses to accept the resource.
       This could also occur when the destination is on another sub-section
       of the same server namespace.
    """

    async def do_move(self, request: DAVRequest) -> DAVResponse:
        if not request.dst_path.startswith(self.prefix):
            # Do not support between DAVProvider instance
            return DAVResponse(400)

        if await self.dav_lock.is_locking(request.src_path):
            return DAVResponse(423)
        if await self.dav_lock.is_locking(request.dst_path):
            return DAVResponse(423)

        http_status = await self._do_move(request)
        # )
        return DAVResponse(http_status)

    async def _do_move(self, request: DAVRequest) -> int:
        raise NotImplementedError

    """
    https://tools.ietf.org/html/rfc4918#page-61
    9.10.  LOCK Method
    9.10.6.  LOCK Responses
    
       In addition to the general status codes possible, the following
       status codes have specific applicability to LOCK:
    
       200 (OK) - The LOCK request succeeded and the value of the DAV:
       lockdiscovery property is included in the response body.
    
       201 (Created) - The LOCK request was to an unmapped URL, the request
       succeeded and resulted in the creation of a new resource, and the
       value of the DAV:lockdiscovery property is included in the response
       body.

       409 (Conflict) - A resource cannot be created at the destination
       until one or more intermediate collections have been created.  The
       server MUST NOT create those intermediate collections automatically.
    
       423 (Locked), potentially with 'no-conflicting-lock' precondition
       code - There is already a lock on the resource that is not compatible
       with the requested lock (see lock compatibility table above).
    
       412 (Precondition Failed), with 'lock-token-matches-request-uri'
       precondition code - The LOCK request was made with an If header,
       indicating that the client wishes to refresh the given lock.
       However, the Request-URI did not fall within the scope of the lock
       identified by the token.  The lock may have a scope that does not
       include the Request-URI, or the lock could have disappeared, or the
       token may be invalid.
    """

    async def do_lock(self, request: DAVRequest) -> DAVResponse:
        # TODO 201, 409, 412
        if (
            not request.body_is_parsed_success
            or not request.lock_token_is_parsed_success
        ):
            return DAVResponse(400)
        elif request.lock_token:
            # refresh
            lock_info = await self.dav_lock.refresh(request.lock_token)
        else:
            # new
            lock_info = await self.dav_lock.new(request)
            if lock_info is None:
                return DAVResponse(423)

        message = self._create_lock_response(lock_info)
        headers = {
            b"Lock-Token": f"opaquelocktoken:{lock_info.token}".encode("utf-8"),
        }
        response = DAVResponse(
            status=200,
            headers=headers,
            content=message,
            response_type=DAVResponseType.XML,
        )
        return response

    def _create_lock_response(self, lock_info: DAVLockInfo) -> bytes:
        lock_discovery = self._create_data_lock_discovery(lock_info)
        data = {
            "D:prop": {
                "@xmlns:D": "DAV:",
                "D:lockdiscovery": lock_discovery,
            }
        }
        return dav_dict2xml(data)

    """
    https://tools.ietf.org/html/rfc4918#page-68
    9.11.  UNLOCK Method
    9.11.1.  Status Codes
    
       In addition to the general status codes possible, the following
       status codes have specific applicability to UNLOCK:
    
       204 (No Content) - Normal success response (rather than 200 OK, since
       200 OK would imply a response body, and an UNLOCK success response
       does not normally contain a body).
    
       400 (Bad Request) - No lock token was provided.
    
       403 (Forbidden) - The currently authenticated principal does not have
       permission to remove the lock.
    
       409 (Conflict), with 'lock-token-matches-request-uri' precondition -
       The resource was not locked, or the request was made to a Request-URI
       that was not within the scope of the lock.
    """

    async def do_unlock(self, request: DAVRequest) -> DAVResponse:
        # TODO 403

        if request.lock_token is None:
            return DAVResponse(409)

        sucess = await self.dav_lock.release(request.lock_token)
        if sucess:
            return DAVResponse(204)

        return DAVResponse(400)

    @staticmethod
    async def get_options(_: DAVRequest) -> DAVResponse:  # TODO
        headers = {
            b"Allow": ",".join(DAV_METHODS).encode("utf-8"),
            b"DAV": b"1, 2",
        }
        return DAVResponse(status=200, headers=headers)
