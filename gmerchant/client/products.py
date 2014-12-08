import bleach
import time

from datetime import datetime

from .api import Content
from apiclient.http import BatchHttpRequest
from oauth2client import client
from googleapiclient import discovery
from oscar.core.loading import get_model
from django.utils.encoding import smart_text



Product = get_model('catalogue','Product')

unique_id_increment = 0
MAX_PAGE_SIZE = 50
BATCH_SIZE = 50
BRAND = "Protein Dynamix"


def get_unique_id(gprod):
  """Generates a unique ID.

  The ID is based on the current UNIX timestamp and a runtime increment.

  Returns:
    A unique string.
  """
  if gprod.google_shopping_id:
    #Return shopping ID from DB if one is set.
    return gprod.google_shopping_id
    
  global unique_id_increment
  if unique_id_increment is None:
    unique_id_increment = 0
  unique_id_increment += 1
  return "%d%d" % (int(time.time()), unique_id_increment)

def chunks(l, n):
    """ Yield successive n-sized chunks from l.
    """
    for i in xrange(0, len(l), n):
        yield l[i:i+n]

def warn_exp_token():
    print ('The credentials have been revoked or expired, please re-run the '
               'application to re-authorize')


class ShoppingClient(object):

    app = None
    service = None
    merchant_id = ""

    def __init__(self,*args,**kwargs):
        self.app = kwargs.get("app",None)
        if not self.app:
            raise AttributeError("You must assign an app to use this.")
        else:
            #import pdb; pdb.set_trace()

            self.merchant_id = self.app.account_id
            content_scheme = Content()
            self.http_auth = content_scheme.serverAuthorisation(self.app.credentials)
            self.service = discovery.build('content', 'v2', http=self.http_auth)


    def batchUpdate(self):

        def product_updated(request_id, unused_response, exception):
          if exception is not None:
            # Do something with the exception.
            print 'There was an error: ' + str(exception)
          else:
            print 'Request ID: %s - Product was updated.' % (str(request_id),)

        merchant_id = self.merchant_id
        product_ids = flags.product_ids

        batch = BatchHttpRequest(callback=product_updated)

        for product_id in product_ids:
            new_status = {
                'availability': 'out of stock',
                'price': {'value': 3.14, 'currency': 'GBP'}}

        # Add product update to the batch.
        batch.add(service.inventory().set(
            merchantId=merchant_id,
            storeCode=product_id.split(':')[0],
            productId=product_id,
            body=new_status))
        try:
            batch.execute()

        except client.AccessTokenRefreshError:
            warn_exp_token()

    def buildProduct(self,product):
        GoogleProduct = get_model('gmerchant','GoogleProduct')
        
        gprod, created = GoogleProduct.objects.get_or_create(product_upc=product.upc, product=product)

        offer_id = 'prod#%s' % get_unique_id(gprod)
        product_data = {
                'offerId': offer_id,
                'title':  smart_text(product.title),
                'description': len(product.google_shopping_description) > 0 and bleach.clean(smart_text(product.google_shopping_description),strip=True) or bleach.clean(smart_text(product.parent.google_shopping_description),strip=True),
                'link': "https://proteindynamix.com" + product.get_absolute_url(),
                'imageLink': product.get_first_image_url(),
                'brand': BRAND,
                'contentLanguage': 'en',
                'targetCountry': 'UK',
                'channel': 'online',
                'availability': 'in stock',
                'condition': 'new',
                'googleProductCategory': product.google_taxonomy.name or 'Health & Beauty > Health Care > Fitness & Nutrition',
                'mpn': product.upc,
                'price': {'value': str(product.stockrecords.first().price_incl_tax), 'currency': 'GBP'},
                'shipping': [{
                    'country': 'UK',
                    'service': 'Standard shipping',
                    'price': {'value': '3.95', 'currency': 'GBP'}
                }],
                #'shippingWeight': {'value': '200', 'unit': 'grams'}
            }
            
        gprod.google_shopping_id = offer_id
        gprod.save()

        return product_data

    def insertProduct(self,product):
        try:

            # Dictify the product
            product_data = self.buildProduct(product)

            # Add product.
            request = self.service.products().insert(merchantId=self.merchant_id,
                                                     body=product_data)

            #Override the URI being set as it's junk!
            #request.uri = "https://www.googleapis.com/content/v2/" + self.merchant_id + "/products?alt=json"

            result = request.execute()
            print ('Product with offerId "%s" and title "%s" was created.' %
                   (result['offerId'], result['title']))

        except client.AccessTokenRefreshError:
            warn_exp_token()


    def batchInsertProducts(self,product_qset):
        GoogleProduct = get_model('gmerchant','GoogleProduct')

        def product_inserted(unused_request_id, response, exception):
          if exception is not None:
            # Do something with the exception.
            print 'There was an error: ' + str(exception)
          else:
            offer_id = smart_text(response['offerId'].encode('ascii', 'ignore'))

            gp = GoogleProduct.objects.get(google_shopping_id=offer_id)
            gp.google_shopping_created = datetime.now()
            gp.save()

            print ('Product with offerId "%s" and title "%s" was created.' %
                   (offer_id, smart_text(response['title'].encode('ascii', 'ignore'))))


        for block in chunks(product_qset,BATCH_SIZE):
            #Build a new batch request for this block of products
            batch = BatchHttpRequest(callback=product_inserted)
            for i in block:
                product = self.buildProduct(i)
                # Add product to the batch.
                batch.add(self.service.products().insert(merchantId=self.merchant_id,
                                                    body=product))
            try:
                import pdb; pdb.set_trace()
                #Let's send this batch off to the Goog.
                batch.execute()
            except client.AccessTokenRefreshError:
                warn_exp_token()

    def listProducts(self):
        try:
            request = self.service.products().list(merchantId=self.merchant_id,
                                                   maxResults=MAX_PAGE_SIZE)
            print request.uri

            while request is not None:
              result = request.execute()
              if 'resources' in result:
                products = result['resources']
                for product in products:
                  print ('Product "%s" with title "%s" was found.' %
                         (smart_text(product['id'].encode('ascii', 'ignore')), smart_text(product['title'].encode('ascii', 'ignore'))))

                request = self.service.products().list_next(request, result)
              else:
                print 'No products were found.'
                break

        except client.AccessTokenRefreshError:
            warn_exp_token()
